from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import (
    QA_ENGINEER_HEADERS,
    RELEASE_MANAGER_HEADERS,
    VIEWER_HEADERS,
    make_test_app,
)


@pytest.mark.asyncio
async def test_health_and_readiness_endpoints(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/api/v1/health", "/api/v1/health/live", "/api/v1/health/ready"):
            response = await client.get(path)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["service"] == "ai-qa-release-engineer"
            assert data["app_name"] == "AI QA & Release Engineer"
            assert data["database"] == "ok"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["x-frame-options"] == "DENY"


def test_production_security_validation_rejects_insecure_defaults() -> None:
    insecure = Settings(app_env="production")
    with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
        create_app(insecure)

    wildcard_cors = Settings(
        app_env="production",
        auth_secret_key="a-very-secure-production-secret-key-at-least-32-bytes",
        cors_origins="*",
    )
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        create_app(wildcard_cors)


@pytest.mark.asyncio
async def test_rbac_and_jwt_token_enforcement(tmp_path: Path) -> None:
    app = make_test_app(tmp_path, auth_require_token=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get("/api/v1/auth/me")
        assert missing.status_code == 401

        tok_resp = await client.post(
            "/api/v1/auth/token",
            json={"email": "lead@acme-qa.local", "role": "qa_engineer"},
        )
        assert tok_resp.status_code == 200
        token = tok_resp.json()["access_token"]

        me_resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_resp.status_code == 200
        assert me_resp.json()["role"] == "qa_engineer"
        assert me_resp.json()["auth_method"] == "bearer_token"

    # Dev header RBAC checks
    dev_app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=dev_app), base_url="http://test") as client:
        viewer_mut = await client.post(
            "/api/v1/testgen/synthesize/openapi",
            headers=VIEWER_HEADERS,
            json={
                "suite_name": "Viewer Blocked",
                "spec_text": (
                    "openapi: 3.0.3\npaths:\n  /ping:\n    get:\n"
                    "      responses:\n        '200':\n          description: ok"
                ),
            },
        )
        assert viewer_mut.status_code == 403

        # Seed and verify qa_engineer cannot decide HITL approval
        seed_res = await client.post("/api/v1/seed/demo", headers=QA_ENGINEER_HEADERS)
        assert seed_res.status_code == 200
        approvals = (
            await client.get("/api/v1/audit/approvals", headers=QA_ENGINEER_HEADERS)
        ).json()
        pending_id = approvals[0]["id"]

        denied = await client.post(
            f"/api/v1/audit/approvals/{pending_id}/decide",
            headers=QA_ENGINEER_HEADERS,
            json={"decision": "approved", "notes": "self approve"},
        )
        assert denied.status_code == 403

        allowed = await client.post(
            f"/api/v1/audit/approvals/{pending_id}/decide",
            headers=RELEASE_MANAGER_HEADERS,
            json={"decision": "approved", "notes": "approved by manager"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["status"] == "approved"
