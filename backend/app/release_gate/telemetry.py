from typing import Any

import httpx

from app.release_gate.evaluator import validate_probe_url
from app.release_gate.schemas import TelemetryPullRequest


async def pull_canary_telemetry(payload: TelemetryPullRequest) -> tuple[float, float]:
    """Pull or compute canary (error_rate_pct, p95_latency_ms) from telemetry source."""
    if payload.source == "simulated":
        return (
            round(float(payload.simulated_error_rate_pct), 4),
            round(float(payload.simulated_p95_latency_ms), 2),
        )

    if payload.source == "otel_snapshot":
        total = max(1, int(payload.total_requests))
        errors = max(0, min(total, int(payload.error_requests)))
        error_rate_pct = round((errors / total) * 100.0, 4)
        p95 = round(float(payload.p95_latency_ms), 2)
        return error_rate_pct, p95

    # prometheus source
    if not payload.prometheus_url.strip():
        raise ValueError("prometheus_url is required when source='prometheus'.")
    validate_probe_url(payload.prometheus_url)
    base_url = payload.prometheus_url.strip().rstrip("/")

    async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
        err_resp = await client.get(
            f"{base_url}/api/v1/query",
            params={"query": payload.error_rate_query},
        )
        err_resp.raise_for_status()
        lat_resp = await client.get(
            f"{base_url}/api/v1/query",
            params={"query": payload.p95_latency_query},
        )
        lat_resp.raise_for_status()

    err_val = _extract_prometheus_scalar(err_resp.json())
    lat_val = _extract_prometheus_scalar(lat_resp.json())
    return round(err_val, 4), round(lat_val, 2)


def _extract_prometheus_scalar(body: dict[str, Any]) -> float:
    data = body.get("data")
    if not isinstance(data, dict):
        raise ValueError("Prometheus response missing 'data' field.")
    result = data.get("result")
    if not isinstance(result, list) or not result:
        raise ValueError("Prometheus query returned empty result series.")
    first = result[0]
    if not isinstance(first, dict):
        raise ValueError("Invalid Prometheus series item.")
    val = first.get("value")
    if not isinstance(val, list) or len(val) < 2:
        raise ValueError("Prometheus series item missing [timestamp, value].")
    return float(val[1])
