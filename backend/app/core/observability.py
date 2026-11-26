import re
import threading
import uuid
from collections import defaultdict

_TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")


def extract_or_create_trace_id(traceparent_header: str | None) -> str:
    """Extract W3C traceparent trace ID or mint a 32-char hex trace ID."""
    if traceparent_header:
        match = _TRACEPARENT_RE.match(traceparent_header.strip().lower())
        if match:
            return match.group(1)
    return uuid.uuid4().hex


class MetricsRegistry:
    """Thread-safe in-memory Prometheus metrics collector for HTTP and rate-limit counters."""

    def __init__(self, service_name: str = "ai-qa-release-engineer") -> None:
        self.service_name = service_name
        self._lock = threading.Lock()
        self._request_counts: dict[tuple[str, str, int], int] = defaultdict(int)
        self._duration_ms_total: float = 0.0
        self._duration_observations: int = 0
        self._rate_limit_rejections_total: int = 0

    def record_request(self, method: str, path: str, status_code: int, duration_ms: float) -> None:
        """Record an HTTP request observation."""
        norm_path = path[:120] or "/"
        with self._lock:
            self._request_counts[(method.upper(), norm_path, status_code)] += 1
            self._duration_ms_total += max(0.0, duration_ms)
            self._duration_observations += 1

    def record_rate_limit_rejection(self) -> None:
        """Increment rate limit 429 rejection counter."""
        with self._lock:
            self._rate_limit_rejections_total += 1

    def render_prometheus(self) -> str:
        """Render collected metrics in Prometheus text exposition format."""
        lines = [
            "# HELP http_requests_total Total HTTP requests handled by the API.",
            "# TYPE http_requests_total counter",
        ]
        with self._lock:
            for (method, path, code), count in sorted(self._request_counts.items()):
                escaped_path = path.replace('"', '\\"')
                lines.append(
                    f'http_requests_total{{service="{self.service_name}",'
                    f'method="{method}",path="{escaped_path}",status="{code}"}} {count}'
                )
            lines.extend(
                [
                    "# HELP http_request_duration_ms_sum Total HTTP request duration in ms.",
                    "# TYPE http_request_duration_ms_sum counter",
                    f'http_request_duration_ms_sum{{service="{self.service_name}"}} '
                    f"{self._duration_ms_total:.3f}",
                    "# HELP http_request_duration_ms_count Total timed HTTP requests.",
                    "# TYPE http_request_duration_ms_count counter",
                    f'http_request_duration_ms_count{{service="{self.service_name}"}} '
                    f"{self._duration_observations}",
                    "# HELP rate_limit_rejections_total Total HTTP 429 rate-limit rejections.",
                    "# TYPE rate_limit_rejections_total counter",
                    f'rate_limit_rejections_total{{service="{self.service_name}"}} '
                    f"{self._rate_limit_rejections_total}",
                ]
            )
        return "\n".join(lines) + "\n"
