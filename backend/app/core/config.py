from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DEV_SECRET = "dev-insecure-secret-change-in-production-32bytes"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    app_name: str = "AI QA & Release Engineer"
    app_slug: str = "ai-qa-release-engineer"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    database_url: str = "sqlite+aiosqlite:///./ai_qa_release_engineer.db"
    auto_create_tables: bool = True
    seed_demo_data: bool = False

    llm_default_provider: Literal["mock", "ollama", "gemini"] = "mock"
    llm_fallback_providers: str = "ollama,gemini,mock"
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "llama-3.1-8b-instruct"
    gemini_api_key: str = ""
    gemini_default_model: str = "gemini-2.5-flash"
    llm_redact_pii_for_cloud: bool = True

    flaky_min_runs: int = 3
    flaky_pass_rate_floor: float = 0.2
    flaky_pass_rate_ceiling: float = 0.9
    regression_max_latency_drift_pct: float = 20.0
    llm_eval_min_score: float = 0.85
    canary_max_error_rate_pct: float = 1.0
    canary_max_p95_latency_ms: float = 500.0

    auth_secret_key: str = _DEFAULT_DEV_SECRET
    auth_require_token: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_fallback_list(self) -> list[str]:
        return [p.strip().lower() for p in self.llm_fallback_providers.split(",") if p.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear cached settings for deterministic test overrides."""
    get_settings.cache_clear()


def validate_production_security(settings: Settings) -> None:
    """Fail fast at startup if insecure defaults remain active in production."""
    if settings.app_env.strip().lower() != "production":
        return

    errors: list[str] = []
    if settings.auth_secret_key == _DEFAULT_DEV_SECRET or len(settings.auth_secret_key) < 32:
        errors.append(
            "AUTH_SECRET_KEY must be overridden with a unique >=32-byte secret in production."
        )
    if "*" in settings.cors_origin_list:
        errors.append("CORS_ORIGINS must not contain wildcard '*' in production.")
    if errors:
        raise RuntimeError("Production security validation failed: " + " | ".join(errors))
