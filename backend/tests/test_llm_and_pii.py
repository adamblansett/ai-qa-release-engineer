import pytest

from app.core.config import Settings
from app.llm.pii import redact_pii
from app.llm.router import LLMRouter


def test_pii_and_ci_secret_scrubber() -> None:
    sample = (
        "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz123456 "
        "AKIAIOSFODNN7EXAMPLE "
        "postgres://admin:topsecret@db.internal:5432/prod "
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMifQ.signature_part "
        "password=SuperSecret99! "
        "user=dev.qa@example.com phone=555-867-5309 ssn=123-45-6789 "
        "-----BEGIN RSA PRIVATE KEY-----\nABC123\n-----END RSA PRIVATE KEY-----"
    )
    res = redact_pii(sample)
    assert res.total_redactions >= 7
    assert "ghp_AbCdEf" not in res.redacted_text
    assert "AKIAIOSFODNN7EXAMPLE" not in res.redacted_text
    assert "topsecret" not in res.redacted_text
    assert "eyJhbGciOi" not in res.redacted_text
    assert "SuperSecret99" not in res.redacted_text
    assert "dev.qa@example.com" not in res.redacted_text
    assert "123-45-6789" not in res.redacted_text
    assert "BEGIN RSA PRIVATE KEY" not in res.redacted_text
    assert "[REDACTED_API_KEY]" in res.redacted_text
    assert "[REDACTED_CREDENTIAL_URI]" in res.redacted_text
    assert "[REDACTED_JWT]" in res.redacted_text
    assert "[REDACTED_EMAIL]" in res.redacted_text
    assert "[REDACTED_PRIVATE_KEY]" in res.redacted_text


@pytest.mark.asyncio
async def test_llm_router_redacts_for_cloud_and_falls_back_to_mock() -> None:
    captured: dict[str, str] = {}

    class SpyGeminiAdapter:
        provider_name = "gemini"
        model_name = "gemini-2.5-flash"

        async def generate(self, prompt: str, system_prompt: str, task_type: str) -> str:
            _ = task_type
            captured["prompt"] = prompt
            captured["system_prompt"] = system_prompt
            return "Cloud triage response"

    settings = Settings(
        llm_default_provider="gemini",
        llm_fallback_providers="mock",
        llm_redact_pii_for_cloud=True,
    )
    router = LLMRouter(settings)
    router.adapters["gemini"] = SpyGeminiAdapter()

    resp = await router.generate(
        prompt="CI token ghp_AbCdEfGhIjKlMnOpQrStUvWxYz123456 failed for alice@example.com",
        system_prompt="Contact ops@example.com",
        task_type="ci_triage",
    )
    assert resp.provider == "gemini"
    assert resp.pii_redacted is True
    assert resp.redaction_count == 3
    assert "ghp_AbCdEf" not in captured["prompt"]
    assert "alice@example.com" not in captured["prompt"]
    assert "ops@example.com" not in captured["system_prompt"]

    # When ollama & gemini fail (empty key / unreachable URL), router falls back to mock
    fallback_settings = Settings(
        llm_default_provider="ollama",
        ollama_base_url="http://127.0.0.1:9",
        llm_fallback_providers="gemini,mock",
        gemini_api_key="",
    )
    fallback_router = LLMRouter(fallback_settings)
    fb_resp = await fallback_router.generate("Check release v1.0.0", task_type="release_gate")
    assert fb_resp.provider == "mock"
    assert "Deterministic release readiness brief" in fb_resp.content
