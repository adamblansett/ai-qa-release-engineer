from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import QA_ENGINEER_HEADERS, make_test_app

HARDENED_WORKFLOW = """name: CI
on:
  pull_request:
    branches: [main]
permissions:
  contents: read
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - run: npm ci && npm test
"""

INSECURE_WORKFLOW = """name: Insecure CI
on:
  pull_request:
    branches: [main]
permissions: write-all
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@main
      - run: echo "${{ github.event.pull_request.title }}" && npm install
      - env:
          TOKEN: ghp_AbCdEfGhIjKlMnOpQrStUvWxYz123456
        run: echo ok
"""


@pytest.mark.asyncio
async def test_ci_log_triage_flaky_clustering_and_workflow_audit(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. OOM classification
        oom_resp = await client.post(
            "/api/v1/ci-triage/analyze",
            headers=QA_ENGINEER_HEADERS,
            json={
                "pipeline_name": "web-ci",
                "branch": "main",
                "commit_sha": "sha-100",
                "job_name": "vitest",
                "raw_log": "FATAL ERROR: JavaScript heap out of memory (exit code 137)",
            },
        )
        assert oom_resp.status_code == 201
        assert oom_resp.json()["root_cause_category"] == "infra_oom"
        assert oom_resp.json()["status"] == "failed"

        # 2. Oscillating test across 4 runs -> flaky cluster, plus stable test
        outcomes = [
            ("sha-1", "passed", ""),
            (
                "sha-2",
                "failed",
                "TimeoutError: waiting for lock 123e4567-e89b-12d3-a456-426614174000",
            ),
            ("sha-3", "passed", ""),
            (
                "sha-4",
                "failed",
                "TimeoutError: waiting for lock 223e4567-e89b-12d3-a456-426614174000",
            ),
        ]
        for sha, out, err_msg in outcomes:
            log_line = (
                f"FAILED tests/test_cart.py::test_race - {err_msg}"
                if out == "failed"
                else "2 passed"
            )
            r = await client.post(
                "/api/v1/ci-triage/analyze",
                headers=QA_ENGINEER_HEADERS,
                json={
                    "pipeline_name": "api-ci",
                    "branch": "main",
                    "commit_sha": sha,
                    "job_name": "pytest",
                    "status": out,
                    "raw_log": log_line,
                    "test_records": [
                        {
                            "test_name": "tests/test_cart.py::test_race",
                            "suite_name": "api",
                            "outcome": out,
                            "error_message": err_msg,
                        },
                        {
                            "test_name": "tests/test_cart.py::test_stable",
                            "suite_name": "api",
                            "outcome": "passed",
                        },
                    ],
                },
            )
            assert r.status_code == 201

        clusters_resp = await client.get(
            "/api/v1/ci-triage/flaky-clusters",
            headers=QA_ENGINEER_HEADERS,
        )
        assert clusters_resp.status_code == 200
        by_name = {c["test_name"]: c for c in clusters_resp.json()}
        flaky = by_name["tests/test_cart.py::test_race"]
        assert flaky["is_flaky"] is True
        assert flaky["transition_count"] == 3
        assert "<UUID>" in flaky["dominant_error_signature"]
        assert by_name["tests/test_cart.py::test_stable"]["is_flaky"] is False

        # 3. GitHub Actions workflow validator
        good_wf = await client.post(
            "/api/v1/ci-triage/workflow-audits",
            headers=QA_ENGINEER_HEADERS,
            json={
                "workflow_name": "Hardened CI",
                "filename": ".github/workflows/ci.yml",
                "workflow_yaml": HARDENED_WORKFLOW,
            },
        )
        assert good_wf.status_code == 201
        assert good_wf.json()["passed"] is True
        assert good_wf.json()["score"] == 100

        bad_wf = await client.post(
            "/api/v1/ci-triage/workflow-audits",
            headers=QA_ENGINEER_HEADERS,
            json={
                "workflow_name": "Insecure CI",
                "filename": ".github/workflows/bad.yml",
                "workflow_yaml": INSECURE_WORKFLOW,
            },
        )
        assert bad_wf.status_code == 201
        bad_data = bad_wf.json()
        assert bad_data["passed"] is False
        rule_ids = {f["rule_id"] for f in bad_data["findings_json"]}
        assert {"WF002", "WF003", "WF004", "WF005", "WF006", "WF007", "WF008"} <= rule_ids
