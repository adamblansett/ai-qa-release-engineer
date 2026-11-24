from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app

RELEASE_MANAGER_HEADERS = {
    "X-Actor-Email": "release-manager@test.local",
    "X-Actor-Role": "release_manager",
}
QA_ENGINEER_HEADERS = {
    "X-Actor-Email": "qa@test.local",
    "X-Actor-Role": "qa_engineer",
}
VIEWER_HEADERS = {
    "X-Actor-Email": "viewer@test.local",
    "X-Actor-Role": "viewer",
}


def make_test_app(tmp_path: Path, **overrides: Any) -> FastAPI:
    """Create an isolated FastAPI app backed by a per-test SQLite file."""
    db_file = tmp_path / "test_qa_release.db"
    cfg = Settings(
        database_url=f"sqlite+aiosqlite:///{db_file.as_posix()}",
        llm_default_provider="mock",
        auto_create_tables=True,
        seed_demo_data=False,
        **overrides,
    )
    return create_app(cfg)
