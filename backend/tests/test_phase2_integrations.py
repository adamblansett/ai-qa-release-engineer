import hashlib
import hmac
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import QA_ENGINEER_HEADERS, RELEASE_MANAGER_HEADERS, make_test_app

JUNIT_XML = """<testsuite name="checkout" tests="2" failures="1">
  <testcase classname="tests.test_api" name="test_health" time="0.05" />
  <testcase classname="tests.test_api" name="test_timeout" time="2.5">
    <failure message="TimeoutError: redis lock exceeded 2000ms">TimeoutError</failure>
  </testcase>
</testsuite>"""

PLAYWRIGHT_JSON = json.dumps(
    {
        "suites": [
            {
                "title": "checkout.spec.ts",
                "specs": [
                    {
                        "title": "submits card payment",
                        "tests": [
                            {
                                "results": [
                                    {
                                        "status": "failed",
                                        "duration": 1450,
                                        "error": {
                                            "message": "TimeoutError: waiting for selector"
                                        },
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        ]
    }
)


@pytest.mark.asyncio
async def test_junit_playwright_ingestion_and_semantic_clustering(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # XXE protection rejects DOCTYPE/ENTITY
        xxe_resp = await client.post(
            "/api/v1/ci-triage/ingest-report",
            headers=QA_ENGINEER_HEADERS,
            json={
                "pipeline_name": "ci",
                "branch": "main",
                "commit_sha": "sha-xxe",
                "job_name": "junit",
                "report_format": "junit_xml",
                "content": '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><testsuite/>',
            },
        )
        assert xxe_resp.status_code == 400

        junit_resp = await client.post(
            "/api/v1/ci-triage/ingest-report",
            headers=QA_ENGINEER_HEADERS,
            json={
                "pipeline_name": "checkout-ci",
                "branch": "feat/a",
                "commit_sha": "sha-j1",
                "job_name": "pytest-junit",
                "report_format": "junit_xml",
                "content": JUNIT_XML,
            },
        )
        assert junit_resp.status_code == 201
        run1_id = junit_resp.json()["id"]
        assert junit_resp.json()["root_cause_category"] == "timeout"

        pw_resp = await client.post(
            "/api/v1/ci-triage/ingest-report",
            headers=QA_ENGINEER_HEADERS,
            json={
                "pipeline_name": "checkout-ci",
                "branch": "feat/b",
                "commit_sha": "sha-p1",
                "job_name": "playwright-e2e",
                "report_format": "playwright_json",
                "content": PLAYWRIGHT_JSON,
            },
        )
        assert pw_resp.status_code == 201
        assert pw_resp.json()["root_cause_category"] == "timeout"

        sim_resp = await client.get(
            f"/api/v1/ci-triage/runs/{run1_id}/similar?limit=5",
            headers=QA_ENGINEER_HEADERS,
        )
        assert sim_resp.status_code == 200
        assert len(sim_resp.json()) >= 1
        assert sim_resp.json()[0]["run_id"] == pw_resp.json()["id"]

        clusters_resp = await client.get(
            "/api/v1/ci-triage/semantic-clusters?threshold=0.1",
            headers=QA_ENGINEER_HEADERS,
        )
        assert clusters_resp.status_code == 200
        assert len(clusters_resp.json()) >= 1


@pytest.mark.asyncio
async def test_github_webhooks_check_publish_telemetry_and_jobs(tmp_path: Path) -> None:
    secret = "whsec_test_secret_123"
    app = make_test_app(tmp_path, github_webhook_secret=secret)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        webhook_body = json.dumps(
            {
                "repository": {"full_name": "adamblansett/ai-qa-release-engineer"},
                "workflow_run": {
                    "name": "Nightly E2E",
                    "conclusion": "failure",
                    "head_branch": "main",
                    "head_sha": "sha-wh-1",
                    "log_excerpt": "AssertionError: status 500",
                },
            }
        ).encode("utf-8")

        bad_sig = await client.post(
            "/api/v1/integrations/github/webhook",
            content=webhook_body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "workflow_run",
                "X-Hub-Signature-256": "sha256=deadbeef",
            },
        )
        assert bad_sig.status_code == 401

        good_sig_val = "sha256=" + hmac.new(
            secret.encode("utf-8"), webhook_body, hashlib.sha256
        ).hexdigest()
        good_wh = await client.post(
            "/api/v1/integrations/github/webhook",
            content=webhook_body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "workflow_run",
                "X-Hub-Signature-256": good_sig_val,
            },
        )
        assert good_wh.status_code == 200
        assert good_wh.json()["created_ci_run_id"] is not None
        ci_run_id = good_wh.json()["created_ci_run_id"]

        # Seed demo release and test telemetry pull + SSRF guard
        await client.post("/api/v1/seed/demo", headers=RELEASE_MANAGER_HEADERS)
        releases = (
            await client.get("/api/v1/release-gate/releases", headers=QA_ENGINEER_HEADERS)
        ).json()
        rel_id = releases[0]["id"]

        ssrf_prom = await client.post(
            f"/api/v1/release-gate/releases/{rel_id}/telemetry/pull",
            headers=QA_ENGINEER_HEADERS,
            json={
                "source": "prometheus",
                "prometheus_url": "http://169.254.169.254",
            },
        )
        assert ssrf_prom.status_code == 400

        otel_pull = await client.post(
            f"/api/v1/release-gate/releases/{rel_id}/telemetry/pull",
            headers=QA_ENGINEER_HEADERS,
            json={
                "source": "otel_snapshot",
                "total_requests": 10000,
                "error_requests": 5,
                "p95_latency_ms": 135.0,
            },
        )
        assert otel_pull.status_code == 200
        assert otel_pull.json()["canary_error_rate_pct"] == 0.05

        # Publish PR Check Run in dry_run mode
        chk = await client.post(
            "/api/v1/integrations/github/publish-check",
            headers=QA_ENGINEER_HEADERS,
            json={
                "repository": "adamblansett/ai-qa-release-engineer",
                "head_sha": "sha-wh-1",
                "release_id": rel_id,
                "ci_run_id": ci_run_id,
                "dry_run": True,
            },
        )
        assert chk.status_code == 200
        assert chk.json()["mode"] == "dry_run"
        assert "AI QA & Release Verification Summary" in chk.json()["summary_markdown"]

        # Enqueue inline background jobs
        sweep = await client.post(
            "/api/v1/jobs/enqueue",
            headers=QA_ENGINEER_HEADERS,
            json={"job_type": "canary_smoke_sweep", "payload_json": {"release_id": rel_id}},
        )
        assert sweep.status_code == 201
        assert sweep.json()["status"] == "completed"
        assert sweep.json()["result_json"]["probe_passed"] is True

        reindex = await client.post(
            "/api/v1/jobs/enqueue",
            headers=QA_ENGINEER_HEADERS,
            json={"job_type": "embedding_reindex", "payload_json": {}},
        )
        assert reindex.status_code == 201
        assert reindex.json()["status"] == "completed"
        assert reindex.json()["result_json"]["reindexed_runs"] >= 1
