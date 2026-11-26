from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from app.core.observability import MetricsRegistry

router = APIRouter(tags=["observability"])


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics(request: Request) -> PlainTextResponse:
    """Expose Prometheus text-format HTTP and rate-limit metrics."""
    registry = getattr(request.app.state, "metrics", None)
    if not isinstance(registry, MetricsRegistry):
        registry = MetricsRegistry()
    return PlainTextResponse(
        content=registry.render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
