from typing import Any, Protocol

import httpx
import structlog
from fastapi import Request
from pydantic import BaseModel

from app.core.config import Settings
from app.llm.pii import redact_pii

logger = structlog.get_logger(__name__)

CLOUD_PROVIDERS = {"gemini"}


class LLMResponse(BaseModel):
    """Unified completion response returned by the LLM router."""

    content: str
    provider: str
    model: str
    pii_redacted: bool = False
    redaction_count: int = 0


class LLMAdapter(Protocol):
    """Protocol implemented by local, cloud, and mock LLM adapters."""

    provider_name: str
    model_name: str

    async def generate(self, prompt: str, system_prompt: str, task_type: str) -> str:
        ...


class MockLLMAdapter:
    """Offline deterministic QA & release engineering generator for CI and local dev."""

    provider_name = "mock"
    model_name = "deterministic-qa-release-v1"

    async def generate(self, prompt: str, system_prompt: str, task_type: str) -> str:
        _ = system_prompt
        compact = " ".join(line.strip() for line in prompt.splitlines() if line.strip())
        if task_type == "testgen_synthesis":
            return (
                "Deterministic TestGen synthesis note: "
                f"{compact[:240]} — Verified schema assertions, negative validation cases, "
                "and auth guard coverage prior to suite publication."
            )
        if task_type == "ci_triage":
            return (
                "Deterministic CI triage analysis: "
                f"{compact[:240]} — Isolated failure signature and prioritized deterministic "
                "remediation before re-running pipeline."
            )
        if task_type == "regression_diff":
            return (
                "Deterministic regression gate brief: "
                f"{compact[:240]} — Evaluated contract compatibility, snapshot paths, "
                "and LLM rubric thresholds against baseline."
            )
        if task_type == "release_gate":
            return (
                "Deterministic release readiness brief: "
                f"{compact[:240]} — Checked smoke probes, canary SLOs, regression status, "
                "and rollback verification prior to human sign-off."
            )
        return f"Deterministic QA summary: {compact[:240]}"


class OllamaLLMAdapter:
    """Local-first open-weights Ollama adapter."""

    provider_name = "ollama"

    def __init__(self, base_url: str, model_name: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name

    async def generate(self, prompt: str, system_prompt: str, task_type: str) -> str:
        _ = task_type
        payload: dict[str, Any] = {
            "model": self.model_name,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            text = str(data.get("response", "")).strip()
            if not text:
                raise RuntimeError("Ollama returned an empty response.")
            return text


class GeminiLLMAdapter:
    """Cloud Gemini adapter guarded by outbound PII and CI secret redaction."""

    provider_name = "gemini"

    def __init__(self, api_key: str, model_name: str) -> None:
        self.api_key = api_key.strip()
        self.model_name = model_name

    async def generate(self, prompt: str, system_prompt: str, task_type: str) -> str:
        _ = task_type
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model_name}:generateContent"
        )
        combined = f"{system_prompt}\n\n{prompt}".strip() if system_prompt else prompt
        body = {
            "contents": [{"role": "user", "parts": [{"text": combined}]}],
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                url,
                params={"key": self.api_key},
                json=body,
            )
            response.raise_for_status()
            data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini returned no candidates.")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(str(p.get("text", "")) for p in parts).strip()
        if not text:
            raise RuntimeError("Gemini returned empty candidate text.")
        return text


class LLMRouter:
    """Routes LLM tasks across mock, local Ollama, and PII-redacted cloud Gemini."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.adapters: dict[str, LLMAdapter] = {
            "mock": MockLLMAdapter(),
            "ollama": OllamaLLMAdapter(
                base_url=settings.ollama_base_url,
                model_name=settings.ollama_default_model,
            ),
            "gemini": GeminiLLMAdapter(
                api_key=settings.gemini_api_key,
                model_name=settings.gemini_default_model,
            ),
        }

    def provider_chain(self) -> list[str]:
        """Build deduplicated provider fallback order starting with default."""
        chain: list[str] = []
        for candidate in [self.settings.llm_default_provider, *self.settings.llm_fallback_list]:
            normalized = candidate.strip().lower()
            if normalized in self.adapters and normalized not in chain:
                chain.append(normalized)
        if "mock" not in chain:
            chain.append("mock")
        return chain

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        task_type: str = "general",
    ) -> LLMResponse:
        """Execute completion using configured provider chain with cloud PII scrubbing."""
        last_error: Exception | None = None
        for provider_name in self.provider_chain():
            adapter = self.adapters[provider_name]
            outbound_prompt = prompt
            outbound_system = system_prompt
            redacted = False
            redaction_count = 0

            if provider_name in CLOUD_PROVIDERS and self.settings.llm_redact_pii_for_cloud:
                prompt_res = redact_pii(prompt)
                sys_res = redact_pii(system_prompt)
                outbound_prompt = prompt_res.redacted_text
                outbound_system = sys_res.redacted_text
                redaction_count = prompt_res.total_redactions + sys_res.total_redactions
                redacted = True

            try:
                content = await adapter.generate(
                    prompt=outbound_prompt,
                    system_prompt=outbound_system,
                    task_type=task_type,
                )
                return LLMResponse(
                    content=content,
                    provider=adapter.provider_name,
                    model=adapter.model_name,
                    pii_redacted=redacted,
                    redaction_count=redaction_count,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm_provider_fallback",
                    provider=provider_name,
                    task_type=task_type,
                    error=str(exc),
                )

        raise RuntimeError(f"All LLM providers failed: {last_error}")


def get_llm_router(request: Request) -> LLMRouter:
    """FastAPI dependency returning the app-scoped LLMRouter."""
    router: LLMRouter = request.app.state.llm_router
    return router
