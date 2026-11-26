from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import QA_ENGINEER_HEADERS, RELEASE_MANAGER_HEADERS, make_test_app


@pytest.mark.asyncio
async def test_api_key_lifecycle_and_enforcement(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # qa_engineer cannot mint API keys
        denied = await client.post(
            "/api/v1/auth/api-keys",
            headers=QA_ENGINEER_HEADERS,
            json={"name": "bot", "role": "qa_engineer", "owner_email": "bot@test.local"},
        )
        assert denied.status_code == 403

        # release_manager provisions key
        created = await client.post(
            "/api/v1/auth/api-keys",
            headers=RELEASE_MANAGER_HEADERS,
            json={
                "name": "ci-pipeline-key",
                "role": "qa_engineer",
                "owner_email": "ci-bot@test.local",
            },
        )
        assert created.status_code == 201
        key_id = created.json()["id"]
        raw_key = created.json()["raw_key"]
        assert raw_key.startswith("qa_live_")

        # Authenticate using X-API-Key
        me_resp = await client.get("/api/v1/auth/me", headers={"X-API-Key": raw_key})
        assert me_resp.status_code == 200
        assert me_resp.json()["auth_method"] == "api_key"
        assert me_resp.json()["email"] == "ci-bot@test.local"
        assert me_resp.json()["role"] == "qa_engineer"

        # Revoke key -> subsequent calls fail with 401
        revoked = await client.delete(
            f"/api/v1/auth/api-keys/{key_id}",
            headers=RELEASE_MANAGER_HEADERS,
        )
        assert revoked.status_code == 200
        assert revoked.json()["revoked_at"] is not None

        rejected = await client.get("/api/v1/auth/me", headers={"X-API-Key": raw_key})
        assert rejected.status_code == 401


@pytest.mark.asyncio
async def test_rate_limit_middleware_and_observability_metrics(tmp_path: Path) -> None:
    app = make_test_app(
        tmp_path,
        rate_limit_enabled=True,
        rate_limit_requests_per_minute=3,
        otel_enabled=True,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(3):
            ok_resp = await client.get("/api/v1/auth/me", headers=QA_ENGINEER_HEADERS)
            assert ok_resp.status_code == 200
            assert "x-trace-id" in ok_resp.headers
            assert ok_resp.headers["x-ratelimit-limit"] == "3"

        limited = await client.get("/api/v1/auth/me", headers=QA_ENGINEER_HEADERS)
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"

        # Health & metrics endpoints remain exempt from rate limits
        health_ok = await client.get("/api/v1/health/live")
        assert health_ok.status_code == 200

        metrics_resp = await client.get("/api/v1/metrics")
        assert metrics_resp.status_code == 200
        assert "http_requests_total" in metrics_resp.text
        assert "rate_limit_rejections_total" in metrics_resp.text
