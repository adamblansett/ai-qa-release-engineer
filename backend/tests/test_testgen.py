from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import QA_ENGINEER_HEADERS, RELEASE_MANAGER_HEADERS, make_test_app

OPENAPI_SPEC = """openapi: 3.0.3
info:
  title: Orders API
  version: 1.0.0
paths:
  /orders:
    post:
      operationId: createOrder
      security:
        - bearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [sku, qty]
              properties:
                sku:
                  type: string
                qty:
                  type: integer
      responses:
        "201":
          description: Created
          content:
            application/json:
              schema:
                type: object
                required: [id, status]
                properties:
                  id:
                    type: string
                  status:
                    type: string
"""


@pytest.mark.asyncio
async def test_openapi_and_user_flow_synthesis_with_hitl(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Playwright OpenAPI synthesis
        pw_resp = await client.post(
            "/api/v1/testgen/synthesize/openapi",
            headers=QA_ENGINEER_HEADERS,
            json={
                "suite_name": "Orders Playwright Suite",
                "spec_text": OPENAPI_SPEC,
                "framework": "playwright",
                "target_base_url": "http://localhost:8000",
                "include_negative_cases": True,
                "include_auth_cases": True,
            },
        )
        assert pw_resp.status_code == 201
        pw_data = pw_resp.json()
        assert pw_data["case_count"] == 3
        categories = {c["category"] for c in pw_data["cases"]}
        assert categories == {"happy_path", "validation", "auth_guard"}
        assert "expect(payload).toHaveProperty(\"id\")" in pw_data["generated_code"]

        # Pytest OpenAPI synthesis
        py_resp = await client.post(
            "/api/v1/testgen/synthesize/openapi",
            headers=QA_ENGINEER_HEADERS,
            json={
                "suite_name": "Orders Pytest Suite",
                "spec_text": OPENAPI_SPEC,
                "framework": "pytest",
                "target_base_url": "http://localhost:8000",
            },
        )
        assert py_resp.status_code == 201
        assert "async def test_createorder_happy" in py_resp.json()["generated_code"]

        # Invalid spec returns 400
        bad_resp = await client.post(
            "/api/v1/testgen/synthesize/openapi",
            headers=QA_ENGINEER_HEADERS,
            json={"suite_name": "Broken", "spec_text": "not_openapi: true"},
        )
        assert bad_resp.status_code == 400

        # User flow synthesis & HITL publication approval
        flow_resp = await client.post(
            "/api/v1/testgen/synthesize/flow",
            headers=QA_ENGINEER_HEADERS,
            json={
                "suite_name": "Login Journey",
                "flow_name": "User Login Flow",
                "target_base_url": "http://localhost:3000",
                "steps": [
                    {"action": "navigate", "target": "/login"},
                    {"action": "fill", "target": "#email", "value": "qa@example.com"},
                    {"action": "click", "target": "button[type='submit']"},
                    {"action": "assert_visible", "target": "[data-testid='dashboard']"},
                ],
            },
        )
        assert flow_resp.status_code == 201
        suite_id = flow_resp.json()["id"]
        assert flow_resp.json()["case_count"] == 2

        req_app = await client.post(
            f"/api/v1/testgen/suites/{suite_id}/request-approval",
            headers=QA_ENGINEER_HEADERS,
        )
        assert req_app.status_code == 200
        approval_id = req_app.json()["id"]

        decide = await client.post(
            f"/api/v1/audit/approvals/{approval_id}/decide",
            headers=RELEASE_MANAGER_HEADERS,
            json={"decision": "approved", "notes": "Ready for nightly CI"},
        )
        assert decide.status_code == 200

        suite_after = await client.get(
            f"/api/v1/testgen/suites/{suite_id}",
            headers=QA_ENGINEER_HEADERS,
        )
        assert suite_after.status_code == 200
        assert suite_after.json()["status"] == "approved"
