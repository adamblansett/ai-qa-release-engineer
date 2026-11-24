from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import QA_ENGINEER_HEADERS, RELEASE_MANAGER_HEADERS, make_test_app


@pytest.mark.asyncio
async def test_contract_snapshot_llm_eval_and_baseline_promotion(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Create combined contract + snapshot baseline
        bl_payload = {
            "latency_p95_ms": 100.0,
            "contracts": {
                "POST /orders": {
                    "status": 201,
                    "required_fields": ["id", "total"],
                    "field_types": {"id": "string", "total": "number"},
                }
            },
            "snapshots": {
                "receipt": {"currency": "USD", "version": 1},
            },
        }
        bl_resp = await client.post(
            "/api/v1/regression/baselines",
            headers=QA_ENGINEER_HEADERS,
            json={
                "suite_name": "orders-suite",
                "service_name": "orders-api",
                "gate_type": "combined",
                "baseline_payload_json": bl_payload,
            },
        )
        assert bl_resp.status_code == 201
        assert bl_resp.json()["version"] == 1

        # 2. Additive contract change + latency warning (30% > 20% tolerance)
        warn_run = await client.post(
            "/api/v1/regression/runs",
            headers=QA_ENGINEER_HEADERS,
            json={
                "suite_name": "orders-suite",
                "commit_sha": "sha-warn",
                "branch": "main",
                "latency_p95_ms": 130.0,
                "candidate_payload_json": {
                    "contracts": {
                        "POST /orders": {
                            "status": 201,
                            "required_fields": ["id", "total"],
                            "field_types": {"id": "string", "total": "number", "note": "string"},
                        }
                    },
                    "snapshots": {"receipt": {"currency": "USD", "version": 1}},
                },
            },
        )
        assert warn_run.status_code == 201
        assert warn_run.json()["status"] == "warning"
        assert warn_run.json()["failed_checks"] == 0

        # 3. Breaking contract change + snapshot diff
        fail_run = await client.post(
            "/api/v1/regression/runs",
            headers=QA_ENGINEER_HEADERS,
            json={
                "suite_name": "orders-suite",
                "commit_sha": "sha-v2",
                "branch": "feat/v2",
                "latency_p95_ms": 105.0,
                "candidate_payload_json": {
                    "contracts": {
                        "POST /orders": {
                            "status": 201,
                            "required_fields": ["id", "total"],
                            "field_types": {"id": "string", "total": "string"},
                        }
                    },
                    "snapshots": {"receipt": {"currency": "USD", "version": 2}},
                },
            },
        )
        assert fail_run.status_code == 201
        fail_data = fail_run.json()
        assert fail_data["status"] == "failed"
        assert fail_data["failed_checks"] == 2

        # Propose baseline promotion & approve via Release Manager
        promo_req = await client.post(
            f"/api/v1/regression/runs/{fail_data['id']}/propose-baseline",
            headers=QA_ENGINEER_HEADERS,
        )
        assert promo_req.status_code == 200
        approval_id = promo_req.json()["id"]

        decide = await client.post(
            f"/api/v1/audit/approvals/{approval_id}/decide",
            headers=RELEASE_MANAGER_HEADERS,
            json={"decision": "approved", "notes": "Intentional v2 schema rollout"},
        )
        assert decide.status_code == 200

        baselines = (
            await client.get("/api/v1/regression/baselines", headers=QA_ENGINEER_HEADERS)
        ).json()
        assert baselines[0]["version"] == 2
        assert baselines[0]["baseline_payload_json"]["snapshots"]["receipt"]["version"] == 2

        # 4. LLM Eval gate detects PII leak
        llm_bl = await client.post(
            "/api/v1/regression/baselines",
            headers=QA_ENGINEER_HEADERS,
            json={
                "suite_name": "eval-suite",
                "service_name": "qa-assistant",
                "gate_type": "llm_eval",
                "baseline_payload_json": {
                    "llm_evals": [
                        {
                            "id": "safe_json",
                            "reference_answer": "Increase memory limit",
                            "required_keywords": ["memory"],
                            "forbidden_terms": ["skip test"],
                            "require_json": True,
                            "baseline_score": 0.9,
                        }
                    ]
                },
            },
        )
        assert llm_bl.status_code == 201

        bad_eval = await client.post(
            "/api/v1/regression/runs",
            headers=QA_ENGINEER_HEADERS,
            json={
                "suite_name": "eval-suite",
                "commit_sha": "sha-leak",
                "branch": "feat/prompt",
                "latency_p95_ms": 200.0,
                "candidate_payload_json": {
                    "llm_eval_outputs": {
                        "safe_json": '{"advice":"Increase memory and email ops@secret.com"}'
                    }
                },
            },
        )
        assert bad_eval.status_code == 201
        assert bad_eval.json()["status"] == "failed"
        assert bad_eval.json()["llm_eval_score"] == 0.0
