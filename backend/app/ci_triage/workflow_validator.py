import re
from typing import Any

import yaml

_UNTRUSTED_EXPR_RE = re.compile(
    r"\$\{\{\s*github\.event\.(?:issue\.title|issue\.body|pull_request\.title|"
    r"pull_request\.body|pull_request\.head\.ref|comment\.body|head_commit\.message)"
)
_HARDCODED_SECRET_RE = re.compile(
    r"(?i)\b(?:ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|"
    r"sk-[A-Za-z0-9_-]{20,})\b"
)
_NPM_INSTALL_RE = re.compile(r"(?i)\bnpm\s+install\b")


def _extract_triggers(data: dict[Any, Any]) -> set[str]:
    on_block = data.get("on")
    if on_block is None and True in data:
        on_block = data.get(True)
    if isinstance(on_block, str):
        return {on_block}
    if isinstance(on_block, list):
        return {str(item) for item in on_block}
    if isinstance(on_block, dict):
        return {str(k) for k in on_block}
    return set()


def _has_permissions(node: Any) -> bool:
    return isinstance(node, dict) and "permissions" in node


def validate_workflow_yaml(workflow_yaml: str) -> tuple[bool, int, list[dict[str, str]]]:
    """Validate a GitHub Actions workflow YAML against WF001-WF008 reliability & security rules."""
    parsed = yaml.safe_load(workflow_yaml)
    if not isinstance(parsed, dict):
        raise ValueError("Workflow YAML must deserialize to a mapping.")

    findings: list[dict[str, str]] = []
    triggers = _extract_triggers(parsed)
    is_pr_trigger = bool(triggers & {"pull_request", "pull_request_target"})
    raw_jobs = parsed.get("jobs")
    jobs: dict[str, Any] = raw_jobs if isinstance(raw_jobs, dict) else {}

    top_perms = parsed.get("permissions")
    has_any_perms = _has_permissions(parsed) or any(
        isinstance(job, dict) and _has_permissions(job) for job in jobs.values()
    )
    if not has_any_perms:
        findings.append(
            {
                "rule_id": "WF001",
                "severity": "high",
                "title": "Missing explicit permissions block",
                "detail": "Workflow does not declare least-privilege GITHUB_TOKEN permissions.",
                "remediation": "Set top-level 'permissions: { contents: read }'.",
            }
        )

    overly_broad = top_perms == "write-all" or (
        isinstance(top_perms, dict) and is_pr_trigger and top_perms.get("contents") == "write"
    )
    if not overly_broad:
        for job in jobs.values():
            if not isinstance(job, dict):
                continue
            jperms = job.get("permissions")
            if jperms == "write-all" or (
                isinstance(jperms, dict) and is_pr_trigger and jperms.get("contents") == "write"
            ):
                overly_broad = True
                break
    if overly_broad:
        findings.append(
            {
                "rule_id": "WF002",
                "severity": "high",
                "title": "Overly broad write permissions",
                "detail": "Workflow grants write-all or contents:write on pull_request triggers.",
                "remediation": "Restrict permissions to read-only scopes unless explicitly needed.",
            }
        )

    jobs_missing_timeout: list[str] = []
    unpinned_actions: list[str] = []
    unsafe_script_injection = False
    uses_npm_install = False

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        if "timeout-minutes" not in job:
            jobs_missing_timeout.append(str(job_id))
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses_val = step.get("uses")
            if (
                isinstance(uses_val, str)
                and not uses_val.startswith("./")
                and ("@" not in uses_val or uses_val.endswith(("@main", "@master", "@HEAD")))
            ):
                unpinned_actions.append(uses_val)
            run_val = step.get("run")
            if isinstance(run_val, str):
                if _UNTRUSTED_EXPR_RE.search(run_val):
                    unsafe_script_injection = True
                if _NPM_INSTALL_RE.search(run_val):
                    uses_npm_install = True

    if jobs_missing_timeout:
        findings.append(
            {
                "rule_id": "WF003",
                "severity": "medium",
                "title": "Job missing timeout-minutes",
                "detail": f"Jobs without timeout-minutes: {', '.join(jobs_missing_timeout)}.",
                "remediation": "Add 'timeout-minutes: 15' to prevent hung runners.",
            }
        )

    if unpinned_actions:
        findings.append(
            {
                "rule_id": "WF004",
                "severity": "medium",
                "title": "Unpinned GitHub Action reference",
                "detail": f"Mutable or untagged actions: {', '.join(unpinned_actions[:5])}.",
                "remediation": "Pin actions to commit SHAs or version tags (e.g. @v4).",
            }
        )

    if is_pr_trigger and "concurrency" not in parsed:
        findings.append(
            {
                "rule_id": "WF005",
                "severity": "low",
                "title": "Missing concurrency cancellation group",
                "detail": "PR workflow lacks concurrency.cancel-in-progress to drop stale runs.",
                "remediation": "Add concurrency group keyed on github.ref with cancel-in-progress.",
            }
        )

    if unsafe_script_injection:
        findings.append(
            {
                "rule_id": "WF006",
                "severity": "high",
                "title": "Potential workflow script injection",
                "detail": (
                    "Untrusted github.event title/body/ref interpolated directly inside run:."
                ),
                "remediation": "Bind untrusted inputs via step env: vars instead of ${{ ... }}.",
            }
        )

    if uses_npm_install:
        findings.append(
            {
                "rule_id": "WF007",
                "severity": "medium",
                "title": "Non-deterministic npm install in CI",
                "detail": "Found 'npm install' instead of lockfile-enforced 'npm ci'.",
                "remediation": "Use 'npm ci' to guarantee reproducible dependency resolution.",
            }
        )

    if _HARDCODED_SECRET_RE.search(workflow_yaml):
        findings.append(
            {
                "rule_id": "WF008",
                "severity": "high",
                "title": "Hardcoded token or credential detected",
                "detail": "Workflow YAML contains a literal API key or token pattern.",
                "remediation": "Store credentials in GitHub Secrets using ${{ secrets.* }}.",
            }
        )

    high_count = sum(1 for f in findings if f["severity"] == "high")
    medium_count = sum(1 for f in findings if f["severity"] == "medium")
    low_count = sum(1 for f in findings if f["severity"] == "low")
    score = max(0, 100 - (high_count * 20) - (medium_count * 10) - (low_count * 5))
    passed = score >= 75 and high_count == 0
    return passed, score, findings
