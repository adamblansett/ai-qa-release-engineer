import hashlib
import hmac
from typing import Any, Literal

import httpx

from app.core.config import Settings
from app.db.models import CiBuildRun, ReleaseCandidate


def verify_github_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """Verify GitHub X-Hub-Signature-256 HMAC-SHA256 digest in constant time."""
    if not secret or not signature_header:
        return False
    cleaned = signature_header.strip()
    if not cleaned.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, cleaned)


def build_check_run_payload(
    *,
    check_name: str,
    head_sha: str,
    release: ReleaseCandidate | None,
    ci_run: CiBuildRun | None,
) -> tuple[Literal["success", "failure", "action_required"], str, str]:
    """Build conclusion, title, and Markdown summary for a GitHub PR Check Run."""
    lines: list[str] = ["## AI QA & Release Verification Summary"]
    conclusion: Literal["success", "failure", "action_required"] = "success"
    title = "All QA and release readiness gates passed"

    if release is not None:
        if release.decision == "go":
            conclusion = "action_required" if release.status == "pending_approval" else "success"
            title = (
                f"{release.service_name} {release.version_tag}: "
                f"GO ({release.readiness_score}/100)"
            )
        else:
            conclusion = "failure"
            title = (
                f"{release.service_name} {release.version_tag}: "
                f"NO-GO ({release.readiness_score}/100)"
            )
        lines.append(
            f"- **Release:** `{release.service_name} {release.version_tag}` "
            f"(`{release.environment}`)"
        )
        lines.append(
            f"- **Readiness:** `{release.readiness_score}/100` "
            f"(`{release.decision.upper()}` · status `{release.status}`)"
        )
        lines.append(
            f"- **Canary Telemetry:** error rate `{release.canary_error_rate_pct:.2f}%`, "
            f"p95 latency `{release.canary_p95_latency_ms:.1f}ms`"
        )
        for gate in release.checklist_json:
            mark = "PASS" if gate.get("passed") else "FAIL"
            lines.append(f"  - [{mark}] **{gate.get('label')}**: {gate.get('detail')}")

    if ci_run is not None:
        if ci_run.status == "failed" and conclusion == "success":
            conclusion = "failure"
            title = f"CI job '{ci_run.job_name}' failed ({ci_run.root_cause_category})"
        lines.append(
            f"- **CI Job:** `{ci_run.pipeline_name} / {ci_run.job_name}` "
            f"(`{ci_run.status}` · `{ci_run.root_cause_category}`)"
        )
        lines.append(f"- **Remediation:** {ci_run.remediation_summary}")

    if release is None and ci_run is None:
        lines.append(f"- Verified commit `{head_sha}` under `{check_name}` with no blockers.")

    return conclusion, title, "\n".join(lines)


async def post_github_check_run(
    *,
    repository: str,
    head_sha: str,
    check_name: str,
    conclusion: str,
    title: str,
    summary_markdown: str,
    settings: Settings,
) -> dict[str, Any]:
    """Post a Check Run to GitHub REST API using configured GITHUB_TOKEN."""
    url = f"{settings.github_api_base_url.rstrip('/')}/repos/{repository}/check-runs"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {settings.github_token.strip()}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = {
        "name": check_name,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": title,
            "summary": summary_markdown,
        },
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {"raw": data}
