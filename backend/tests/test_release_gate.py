from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import QA_ENGINEER_HEADERS, RELEASE_MANAGER_HEADERS, make_test_app


@pytest.mark.asyncio
async def test_release_gate_ssrf_probes_checklist_and_hitl_rollback(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create passing regression baseline + run for commit sha-rel1
        await client.post(
            "/api/v1/regression/baselines",
            headers=QA_ENGINEER_HEADERS,
            json={
                "suite_name": "rel-suite",
                "service_name": "billing-api",
                "gate_type": "contract",
                "baseline_payload_json": {
                    "contracts": {
                        "GET /health": {
                            "status": 200,
                            "required_fields": ["status"],
                            "field_types": {"status": "string"},
                        }
                    }
                },
            },
        )
        reg_run = (
            await client.post(
                "/api/v1/regression/runs",
                headers=QA_ENGINEER_HEADERS,
                json={
                    "suite_name": "rel-suite",
                    "commit_sha": "sha-rel1",
                    "branch": "main",
                    "latency_p95_ms": 120.0,
                    "candidate_payload_json": {
                        "contracts": {
                            "GET /health": {
                                "status": 200,
                                "required_fields": ["status"],
                                "field_types": {"status": "string"},
                            }
                        }
                    },
                },
            )
        ).json()

        # Register release candidate without smoke probes -> NO_GO
        rel_resp = await client.post(
            "/api/v1/release-gate/releases",
            headers=QA_ENGINEER_HEADERS,
            json={
                "version_tag": "v1.2.0",
                "service_name": "billing-api",
                "environment": "production",
                "commit_sha": "sha-rel1",
                "previous_version_tag": "v1.1.9",
                "rollback_runbook_url": "https://runbooks.internal/billing",
                "rollback_verified": True,
                "canary_error_rate_pct": 0.2,
                "canary_p95_latency_ms": 180.0,
                "regression_run_id": reg_run["id"],
            },
        )
        assert rel_resp.status_code == 201
        rel_id = rel_resp.json()["id"]
        assert rel_resp.json()["decision"] == "no_go"

        # SSRF protection rejects cloud metadata IP and file:// scheme
        ssrf_ip = await client.post(
            f"/api/v1/release-gate/releases/{rel_id}/probes",
            headers=QA_ENGINEER_HEADERS,
            json={
                "probes": [
                    {
                        "probe_name": "ssrf-meta",
                        "target_url": "http://169.254.169.254/latest/meta-data",
                        "mode": "live_http",
                    }
                ]
            },
        )
        assert ssrf_ip.status_code == 400

        ssrf_scheme = await client.post(
            f"/api/v1/release-gate/releases/{rel_id}/probes",
            headers=QA_ENGINEER_HEADERS,
            json={
                "probes": [
                    {
                        "probe_name": "ssrf-file",
                        "target_url": "file:///etc/passwd",
                        "mode": "simulated",
                    }
                ]
            },
        )
        assert ssrf_scheme.status_code == 400

        # Execute passing smoke probe -> transitions to 100/100 GO
        probe_ok = await client.post(
            f"/api/v1/release-gate/releases/{rel_id}/probes",
            headers=QA_ENGINEER_HEADERS,
            json={
                "probes": [
                    {
                        "probe_name": "ready-check",
                        "target_url": "https://canary.billing.internal/api/v1/health/ready",
                        "expected_status": 200,
                        "expected_body_contains": "ok",
                        "mode": "simulated",
                        "simulated_status": 200,
                        "simulated_latency_ms": 42.0,
                        "simulated_body": '{"status":"ok"}',
                    }
                ]
            },
        )
        assert probe_ok.status_code == 200
        assert probe_ok.json()["readiness_score"] == 100
        assert probe_ok.json()["decision"] == "go"

        # Request promotion and approve
        promo_req = await client.post(
            f"/api/v1/release-gate/releases/{rel_id}/request-promotion",
            headers=QA_ENGINEER_HEADERS,
        )
        assert promo_req.status_code == 200
        await client.post(
            f"/api/v1/audit/approvals/{promo_req.json()['id']}/decide",
            headers=RELEASE_MANAGER_HEADERS,
            json={"decision": "approved", "notes": "Promote to 100% traffic"},
        )
        rel_after_promo = (
            await client.get(f"/api/v1/release-gate/releases/{rel_id}", headers=QA_ENGINEER_HEADERS)
        ).json()
        assert rel_after_promo["status"] == "approved"

        # Trigger HITL rollback -> status becomes rolled_back
        rb_req = await client.post(
            f"/api/v1/release-gate/releases/{rel_id}/request-rollback",
            headers=QA_ENGINEER_HEADERS,
        )
        assert rb_req.status_code == 200
        await client.post(
            f"/api/v1/audit/approvals/{rb_req.json()['id']}/decide",
            headers=RELEASE_MANAGER_HEADERS,
            json={"decision": "approved", "notes": "Post-deploy anomaly detected"},
        )
        rel_after_rb = (
            await client.get(f"/api/v1/release-gate/releases/{rel_id}", headers=QA_ENGINEER_HEADERS)
        ).json()
        assert rel_after_rb["status"] == "rolled_back"
        assert rel_after_rb["rollback_executed_at"] is not None
