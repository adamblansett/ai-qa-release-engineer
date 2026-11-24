import ipaddress
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.db.models import CiBuildRun, RegressionRun, ReleaseCandidate, SmokeProbeResult
from app.release_gate.schemas import SmokeProbeInput

_BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata",
    "169.254.169.254",
    "169.254.170.2",
    "fd00:ec2::254",
}


def validate_probe_url(target_url: str) -> None:
    """Validate smoke probe URL against SSRF and unsafe scheme targets."""
    parsed = urlparse(target_url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(
            f"Unsupported probe URL scheme '{parsed.scheme}'; only http/https are allowed."
        )
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("Probe URL must include a valid hostname.")
    if host in _BLOCKED_HOSTS:
        raise ValueError(f"Probe target host '{host}' is blocked by SSRF protection.")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return

    if ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        raise ValueError(f"Probe IP address '{host}' is blocked by SSRF protection.")


async def execute_smoke_probe(probe: SmokeProbeInput) -> dict[str, Any]:
    """Execute a smoke probe in deterministic simulated mode or guarded live HTTP mode."""
    validate_probe_url(probe.target_url)

    if probe.mode == "simulated":
        actual_status = (
            probe.simulated_status
            if probe.simulated_status is not None
            else probe.expected_status
        )
        latency_ms = round(probe.simulated_latency_ms, 2)
        body_text = probe.simulated_body
        errors: list[str] = []
        if actual_status != probe.expected_status:
            errors.append(f"Expected status {probe.expected_status}, got {actual_status}.")
        if latency_ms > probe.max_latency_ms:
            errors.append(f"Latency {latency_ms}ms exceeded max {probe.max_latency_ms}ms.")
        if probe.expected_body_contains and probe.expected_body_contains not in body_text:
            errors.append(
                f"Response body missing expected substring '{probe.expected_body_contains}'."
            )
        return {
            "actual_status": actual_status,
            "latency_ms": latency_ms,
            "passed": len(errors) == 0,
            "error_detail": " ".join(errors),
        }

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            resp = await client.request(probe.http_method, probe.target_url)
        latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
        errors = []
        if resp.status_code != probe.expected_status:
            errors.append(f"Expected status {probe.expected_status}, got {resp.status_code}.")
        if latency_ms > probe.max_latency_ms:
            errors.append(f"Latency {latency_ms}ms exceeded max {probe.max_latency_ms}ms.")
        if probe.expected_body_contains and probe.expected_body_contains not in resp.text:
            errors.append(
                f"Response body missing expected substring '{probe.expected_body_contains}'."
            )
        return {
            "actual_status": resp.status_code,
            "latency_ms": latency_ms,
            "passed": len(errors) == 0,
            "error_detail": " ".join(errors),
        }
    except httpx.HTTPError as exc:
        latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return {
            "actual_status": None,
            "latency_ms": latency_ms,
            "passed": False,
            "error_detail": f"HTTP probe failed: {exc}",
        }


def evaluate_release_checklist(
    *,
    release: ReleaseCandidate,
    probes: list[SmokeProbeResult],
    regression_run: RegressionRun | None,
    blocking_ci_runs: list[CiBuildRun],
    settings: Settings,
) -> tuple[int, str, list[dict[str, Any]]]:
    """Evaluate the 6-gate release readiness checklist and return score, decision, checklist."""
    latest_by_name: dict[str, SmokeProbeResult] = {}
    for probe in sorted(probes, key=lambda p: p.executed_at):
        latest_by_name[probe.probe_name] = probe

    latest_probes = list(latest_by_name.values())
    probes_ok = bool(latest_probes) and all(p.passed for p in latest_probes)
    if not latest_probes:
        probe_detail = "No smoke probes executed yet."
    elif probes_ok:
        probe_detail = f"All {len(latest_probes)} post-deploy smoke probe(s) passed."
    else:
        failing = [p.probe_name for p in latest_probes if not p.passed]
        probe_detail = f"Failing smoke probe(s): {', '.join(failing)}."

    err_ok = release.canary_error_rate_pct <= settings.canary_max_error_rate_pct
    err_detail = (
        f"Canary error rate {release.canary_error_rate_pct:.2f}% "
        f"(limit {settings.canary_max_error_rate_pct:.2f}%)."
    )

    lat_ok = release.canary_p95_latency_ms <= settings.canary_max_p95_latency_ms
    lat_detail = (
        f"Canary p95 latency {release.canary_p95_latency_ms:.1f}ms "
        f"(limit {settings.canary_max_p95_latency_ms:.1f}ms)."
    )

    if regression_run is None:
        reg_ok = False
        reg_detail = "No regression gate run linked to this release candidate."
    elif regression_run.status in {"passed", "warning"}:
        reg_ok = True
        reg_detail = (
            f"Regression suite '{regression_run.suite_name}' {regression_run.status} "
            f"({regression_run.passed_checks}/{regression_run.total_checks} checks)."
        )
    else:
        reg_ok = False
        reg_detail = (
            f"Regression suite '{regression_run.suite_name}' failed "
            f"({regression_run.failed_checks} failing check(s))."
        )

    rollback_ok = (
        bool(release.previous_version_tag.strip())
        and bool(release.rollback_runbook_url.strip())
        and release.rollback_verified
    )
    if rollback_ok:
        rollback_detail = (
            f"Rollback target {release.previous_version_tag} verified with runbook."
        )
    else:
        rollback_detail = (
            "Requires previous_version_tag, rollback_runbook_url, and rollback_verified=true."
        )

    ci_ok = len(blocking_ci_runs) == 0
    if ci_ok:
        ci_detail = f"No blocking CI build failures for commit {release.commit_sha}."
    else:
        jobs = ", ".join(r.job_name for r in blocking_ci_runs[:3])
        ci_detail = f"Blocking failed CI job(s) on {release.commit_sha}: {jobs}."

    checklist = [
        {
            "gate": "smoke_probes_green",
            "label": "Post-Deploy Smoke Probes",
            "passed": probes_ok,
            "detail": probe_detail,
        },
        {
            "gate": "canary_error_rate_ok",
            "label": "Canary Error Rate SLO",
            "passed": err_ok,
            "detail": err_detail,
        },
        {
            "gate": "canary_latency_ok",
            "label": "Canary p95 Latency SLO",
            "passed": lat_ok,
            "detail": lat_detail,
        },
        {
            "gate": "regression_gate_passed",
            "label": "Contract / Snapshot / Eval Regression Gate",
            "passed": reg_ok,
            "detail": reg_detail,
        },
        {
            "gate": "rollback_readiness_verified",
            "label": "Rollback Target & Runbook Verified",
            "passed": rollback_ok,
            "detail": rollback_detail,
        },
        {
            "gate": "no_blocking_ci_failures",
            "label": "CI Build Health Clean",
            "passed": ci_ok,
            "detail": ci_detail,
        },
    ]

    passed_count = sum(1 for item in checklist if item["passed"])
    score = round((passed_count / len(checklist)) * 100)
    decision = "go" if passed_count == len(checklist) else "no_go"
    return score, decision, checklist
