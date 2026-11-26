import asyncio
from pathlib import Path

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, update

from alembic import command
from app.db.models import AuditEvent
from app.db.session import build_engine
from tests.conftest import QA_ENGINEER_HEADERS, RELEASE_MANAGER_HEADERS, make_test_app


@pytest.mark.asyncio
async def test_seed_idempotency_overview_and_audit_tamper_detection(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/v1/seed/demo", headers=RELEASE_MANAGER_HEADERS)
        assert first.status_code == 200
        assert first.json()["seeded"] is True
        assert first.json()["test_suites"] == 2
        assert first.json()["ci_runs"] == 6
        assert first.json()["regression_runs"] == 3
        assert first.json()["release_candidates"] == 2

        second = await client.post("/api/v1/seed/demo", headers=RELEASE_MANAGER_HEADERS)
        assert second.status_code == 200
        assert second.json()["seeded"] is False

        # Reset forbidden for qa_engineer, allowed for release_manager
        reset_denied = await client.post(
            "/api/v1/seed/demo?reset=true",
            headers=QA_ENGINEER_HEADERS,
        )
        assert reset_denied.status_code == 403

        overview = await client.get("/api/v1/overview", headers=RELEASE_MANAGER_HEADERS)
        assert overview.status_code == 200
        ov = overview.json()
        assert ov["test_suites_count"] == 2
        assert ov["flaky_tests_count"] >= 1
        assert ov["go_releases_count"] == 1
        assert ov["blocked_releases_count"] == 1
        assert ov["audit_chain_valid"] is True

        verify_ok = await client.get("/api/v1/audit/events/verify", headers=RELEASE_MANAGER_HEADERS)
        assert verify_ok.status_code == 200
        assert verify_ok.json()["valid"] is True

        # Tamper directly with sequence #1 in DB and confirm chain verification detects it
        async with app.state.session_factory() as session:
            await session.execute(
                update(AuditEvent)
                .where(AuditEvent.sequence_no == 1)
                .values(action="tampered_action")
            )
            await session.commit()

        verify_bad = await client.get(
            "/api/v1/audit/events/verify", headers=RELEASE_MANAGER_HEADERS
        )
        assert verify_bad.status_code == 200
        assert verify_bad.json()["valid"] is False
        assert verify_bad.json()["broken_sequence_no"] == 1


def test_alembic_initial_migration_creates_all_tables(tmp_path: Path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "alembic_test.db"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(alembic_cfg, "head")

    async def _inspect_schema() -> tuple[set[str], set[str]]:
        engine = build_engine(db_url)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(
                    lambda sync_conn: (
                        set(inspect(sync_conn).get_table_names()),
                        {
                            col["name"]
                            for col in inspect(sync_conn).get_columns("ci_build_runs")
                        },
                    )
                )
        finally:
            await engine.dispose()

    tables, ci_columns = asyncio.run(_inspect_schema())
    expected = {
        "audit_events",
        "approval_requests",
        "test_suites",
        "generated_test_cases",
        "ci_build_runs",
        "test_execution_records",
        "workflow_audits",
        "regression_baselines",
        "regression_runs",
        "release_candidates",
        "smoke_probe_results",
        "api_keys",
        "background_jobs",
        "alembic_version",
    }
    assert expected <= tables
    assert "embedding_json" in ci_columns
