import json
import time
import uuid
from collections import defaultdict, deque

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.observability import MetricsRegistry, extract_or_create_trace_id

_RATE_LIMIT_EXEMPT_PATHS = {
    "/api/v1/health",
    "/api/v1/health/live",
    "/api/v1/health/ready",
    "/metrics",
    "/api/v1/metrics",
}


class SecurityHeadersMiddleware:
    """Pure ASGI middleware injecting security headers, trace IDs, and metrics."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id: str | None = None
        traceparent: str | None = None
        for key, value in scope.get("headers") or []:
            lower_key = key.decode("latin-1").lower()
            if lower_key == "x-request-id":
                candidate = value.decode("latin-1", errors="ignore").strip()[:128]
                if candidate:
                    request_id = candidate
            elif lower_key == "traceparent":
                traceparent = value.decode("latin-1", errors="ignore").strip()[:128]

        resolved_id = request_id or str(uuid.uuid4())
        trace_id = extract_or_create_trace_id(traceparent) if self.settings.otel_enabled else None
        start_time = time.perf_counter()
        method = str(scope.get("method", "GET"))
        path = str(scope.get("path", "/"))
        app_obj = scope.get("app")
        metrics = getattr(getattr(app_obj, "state", None), "metrics", None)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                existing = {k.lower() for k, _ in headers}

                def _set_header(name: bytes, val: bytes) -> None:
                    if name.lower() not in existing:
                        headers.append((name, val))
                        existing.add(name.lower())

                _set_header(b"x-request-id", resolved_id.encode("latin-1"))
                if trace_id is not None:
                    _set_header(b"x-trace-id", trace_id.encode("latin-1"))
                _set_header(b"x-content-type-options", b"nosniff")
                _set_header(b"x-frame-options", b"DENY")
                _set_header(b"referrer-policy", b"strict-origin-when-cross-origin")
                _set_header(
                    b"permissions-policy",
                    b"camera=(), microphone=(), geolocation=()",
                )
                if self.settings.app_env.strip().lower() == "production":
                    _set_header(
                        b"strict-transport-security",
                        b"max-age=31536000; includeSubDomains",
                    )
                if isinstance(metrics, MetricsRegistry):
                    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                    metrics.record_request(method, path, int(message["status"]), elapsed_ms)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RateLimitMiddleware:
    """Pure ASGI sliding-window per-client rate limiter."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self._windows: dict[str, deque[float]] = defaultdict(deque)

    def _client_key(self, scope: Scope) -> str:
        for key, value in scope.get("headers") or []:
            if key.decode("latin-1").lower() == "x-api-key":
                api_key = value.decode("latin-1", errors="ignore").strip()
                if api_key:
                    return f"key:{api_key[:16]}"
        client = scope.get("client")
        if isinstance(client, tuple | list) and client:
            return f"ip:{client[0]}"
        return "ip:unknown"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", "/"))
        if path in _RATE_LIMIT_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        limit = max(1, self.settings.rate_limit_requests_per_minute)
        now = time.monotonic()
        cutoff = now - 60.0
        bucket = self._windows[self._client_key(scope)]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            app_obj = scope.get("app")
            metrics = getattr(getattr(app_obj, "state", None), "metrics", None)
            if isinstance(metrics, MetricsRegistry):
                metrics.record_rate_limit_rejection()
            body = json.dumps(
                {"detail": "Rate limit exceeded. Try again shortly."}
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", b"60"),
                        (b"x-ratelimit-limit", str(limit).encode("latin-1")),
                        (b"x-ratelimit-remaining", b"0"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        bucket.append(now)
        remaining = max(0, limit - len(bucket))

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"x-ratelimit-limit", str(limit).encode("latin-1")))
                headers.append((b"x-ratelimit-remaining", str(remaining).encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
