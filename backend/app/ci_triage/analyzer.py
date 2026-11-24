import re
from collections import defaultdict
from dataclasses import dataclass

from app.ci_triage.schemas import FlakyClusterOut, TestExecutionInput
from app.core.config import Settings
from app.db.models import TestExecutionRecord

_PYTEST_FAIL_RE = re.compile(r"^FAILED\s+([^\s]+)(?:\s*-\s*(.+))?$")
_VITEST_FAIL_RE = re.compile(r"^(?:FAIL|×|✕)\s+(.+)$")
_PLAYWRIGHT_FAIL_RE = re.compile(r"^\s*\d+\)\s+\[[^\]]+\]\s+›\s+([^\s]+(?:\s+›\s+.+)?)$")
_ERROR_LINE_RE = re.compile(
    r"(?:AssertionError|TypeError|ValueError|RuntimeError|TimeoutError|"
    r"ModuleNotFoundError|ImportError|SyntaxError|MemoryError|"
    r"ERR_OOM|Killed|ENOSPC|ECONNREFUSED|ETIMEDOUT|Error:)\b.*"
)

_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
_PORT_RE = re.compile(r":\d{4,5}\b")
_LINE_NUM_RE = re.compile(r":line \d+|:\d+:\d+")


@dataclass(frozen=True)
class _ClassificationRule:
    category: str
    confidence: float
    pattern: re.Pattern[str]
    remediation: str


_CLASSIFICATION_RULES: tuple[_ClassificationRule, ...] = (
    _ClassificationRule(
        category="infra_oom",
        confidence=0.95,
        pattern=re.compile(
            r"(?i)\b(?:out of memory|oom[- ]?kill|memoryerror|exit code 137|"
            r"heap out of memory|enospc|no space left on device)\b"
        ),
        remediation=(
            "Increase runner memory/NODE_OPTIONS=--max-old-space-size or shard test matrix jobs."
        ),
    ),
    _ClassificationRule(
        category="timeout",
        confidence=0.92,
        pattern=re.compile(
            r"(?i)\b(?:timed?\s*out|timeouterror|exceeded timeout|etimedout|"
            r"deadline exceeded|waiting for selector.*failed)\b"
        ),
        remediation=(
            "Replace fixed sleeps with deterministic readiness assertions and inspect slow paths."
        ),
    ),
    _ClassificationRule(
        category="auth_secret_error",
        confidence=0.93,
        pattern=re.compile(
            r"(?i)\b(?:401 unauthorized|403 forbidden|invalid token|missing api key|"
            r"secret.*not set|permission denied|authentication failed)\b"
        ),
        remediation=(
            "Verify CI secret bindings, token permissions, and least-privilege workflow grants."
        ),
    ),
    _ClassificationRule(
        category="dependency_error",
        confidence=0.91,
        pattern=re.compile(
            r"(?i)\b(?:modulenotfounderror|importerror|cannot find module|"
            r"could not resolve dependency|npm err!.*eresolve|econnrefused.*registry)\b"
        ),
        remediation=(
            "Pin lockfiles (npm ci / pinned Python wheels) and verify dependency cache integrity."
        ),
    ),
    _ClassificationRule(
        category="lint_type_error",
        confidence=0.90,
        pattern=re.compile(
            r"(?i)\b(?:mypy|ruff|tsc\b|error ts\d+|found \d+ error|eslint|typecheck failed)\b"
        ),
        remediation="Resolve static type/lint diagnostics locally before pushing to CI.",
    ),
    _ClassificationRule(
        category="build_compile_error",
        confidence=0.88,
        pattern=re.compile(
            r"(?i)\b(?:syntaxerror|build failed|compilation failed|vite build.*error|"
            r"docker build.*failed)\b"
        ),
        remediation="Fix compilation or bundle errors and verify clean container build locally.",
    ),
    _ClassificationRule(
        category="assertion_failure",
        confidence=0.86,
        pattern=re.compile(
            r"(?i)\b(?:assertionerror|expect\(.*\)\.to|assert\s+.*==|failed\s+tests?)\b"
        ),
        remediation=(
            "Inspect failing test diff and contract expectations for functional regression."
        ),
    ),
)


def normalize_signature(text: str) -> str:
    """Normalize log/error text into a stable signature for grouping across runs."""
    cleaned = _TS_RE.sub("<TS>", text.strip())
    cleaned = _UUID_RE.sub("<UUID>", cleaned)
    cleaned = _HEX_RE.sub("<HEX>", cleaned)
    cleaned = _LINE_NUM_RE.sub(":<LINE>", cleaned)
    cleaned = _PORT_RE.sub(":<PORT>", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:240]


def parse_ci_log(raw_log: str) -> tuple[list[dict[str, str]], list[TestExecutionInput]]:
    """Extract structured error lines and test failure records from CI logs."""
    extracted_errors: list[dict[str, str]] = []
    parsed_tests: list[TestExecutionInput] = []
    seen_errors: set[str] = set()

    for line in raw_log.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        pytest_m = _PYTEST_FAIL_RE.match(stripped)
        if pytest_m:
            test_name = pytest_m.group(1)
            msg = (pytest_m.group(2) or stripped).strip()
            sig = normalize_signature(msg)
            parsed_tests.append(
                TestExecutionInput(
                    test_name=test_name,
                    suite_name="pytest",
                    outcome="failed",
                    error_message=msg,
                )
            )
            if sig not in seen_errors:
                seen_errors.add(sig)
                extracted_errors.append(
                    {"test_name": test_name, "signature": sig, "message": msg[:300]}
                )
            continue

        vitest_m = _VITEST_FAIL_RE.match(stripped)
        if vitest_m:
            detail = vitest_m.group(1).strip()
            sig = normalize_signature(detail)
            parsed_tests.append(
                TestExecutionInput(
                    test_name=detail[:200],
                    suite_name="vitest",
                    outcome="failed",
                    error_message=detail,
                )
            )
            if sig not in seen_errors:
                seen_errors.add(sig)
                extracted_errors.append(
                    {"test_name": detail[:120], "signature": sig, "message": detail[:300]}
                )
            continue

        pw_m = _PLAYWRIGHT_FAIL_RE.match(stripped)
        if pw_m:
            test_name = pw_m.group(1).strip()
            sig = normalize_signature(test_name)
            parsed_tests.append(
                TestExecutionInput(
                    test_name=test_name[:250],
                    suite_name="playwright",
                    outcome="failed",
                    error_message=stripped,
                )
            )
            if sig not in seen_errors:
                seen_errors.add(sig)
                extracted_errors.append(
                    {"test_name": test_name[:120], "signature": sig, "message": stripped[:300]}
                )
            continue

        err_m = _ERROR_LINE_RE.search(stripped)
        if err_m:
            msg = err_m.group(0).strip()
            sig = normalize_signature(msg)
            if sig not in seen_errors:
                seen_errors.add(sig)
                extracted_errors.append(
                    {"test_name": "ci_job", "signature": sig, "message": msg[:300]}
                )

    return extracted_errors[:25], parsed_tests


def classify_root_cause(
    *,
    raw_log: str,
    status_hint: str | None,
    extracted_errors: list[dict[str, str]],
) -> tuple[str, str, str, float, str]:
    """Deterministically classify CI build status and root-cause category."""
    has_failure_signal = bool(extracted_errors) or bool(
        re.search(r"(?im)\b(?:failed|failure|error:|exit code [1-9]\d*|fatal:)\b", raw_log)
    )
    resolved_status = status_hint or ("failed" if has_failure_signal else "passed")

    if resolved_status == "passed" and not extracted_errors:
        return (
            "passed",
            "none",
            "BUILD_PASSED",
            1.0,
            "All checks passed with no detected error signatures.",
        )

    for rule in _CLASSIFICATION_RULES:
        if rule.pattern.search(raw_log):
            sig = (
                extracted_errors[0]["signature"]
                if extracted_errors
                else f"{rule.category.upper()}_DETECTED"
            )
            return (
                resolved_status,
                rule.category,
                sig,
                rule.confidence,
                rule.remediation,
            )

    if resolved_status == "failed":
        sig = (
            extracted_errors[0]["signature"]
            if extracted_errors
            else "UNCLASSIFIED_BUILD_FAILURE"
        )
        return (
            "failed",
            "assertion_failure" if extracted_errors else "build_compile_error",
            sig,
            0.7,
            "Review extracted failure signatures and re-run failing job with verbose diagnostics.",
        )

    return (
        resolved_status,
        "none",
        "BUILD_PASSED",
        1.0,
        "Build completed cleanly.",
    )


def compute_flaky_clusters(
    records: list[TestExecutionRecord],
    settings: Settings,
) -> list[FlakyClusterOut]:
    """Cluster test execution history and flag oscillating flaky tests."""
    grouped: dict[str, list[TestExecutionRecord]] = defaultdict(list)
    for rec in records:
        grouped[rec.test_name].append(rec)

    clusters: list[FlakyClusterOut] = []
    for test_name, items in grouped.items():
        ordered = sorted(items, key=lambda r: r.created_at)
        outcomes = [r.outcome for r in ordered if r.outcome in {"passed", "failed"}]
        pass_count = sum(1 for o in outcomes if o == "passed")
        fail_count = sum(1 for o in outcomes if o == "failed")
        executed = pass_count + fail_count
        if executed == 0:
            continue

        pass_rate = round(pass_count / executed, 4)
        transitions = sum(
            1 for idx in range(1, len(outcomes)) if outcomes[idx] != outcomes[idx - 1]
        )
        entropy_component = 4.0 * pass_rate * (1.0 - pass_rate)
        transition_component = transitions / max(1, len(outcomes) - 1)
        flakiness_score = round(
            min(1.0, 0.5 * entropy_component + 0.5 * transition_component),
            4,
        )

        is_flaky = (
            executed >= settings.flaky_min_runs
            and pass_count > 0
            and fail_count > 0
            and (
                settings.flaky_pass_rate_floor <= pass_rate <= settings.flaky_pass_rate_ceiling
                or transitions >= 1
            )
        )

        sig_counts: dict[str, int] = defaultdict(int)
        for rec in ordered:
            if rec.outcome == "failed" and rec.error_signature:
                sig_counts[rec.error_signature] += 1
        dominant_sig = (
            max(sig_counts.items(), key=lambda kv: kv[1])[0] if sig_counts else "NONE"
        )

        recommendation = (
            "Quarantine flaky test, replace implicit timing assumptions, and add retry tracing."
            if is_flaky
            else ("Investigate deterministic failure." if pass_rate == 0.0 else "Stable")
        )

        clusters.append(
            FlakyClusterOut(
                test_name=test_name,
                suite_name=ordered[-1].suite_name,
                total_runs=len(ordered),
                pass_count=pass_count,
                fail_count=fail_count,
                pass_rate=pass_rate,
                transition_count=transitions,
                flakiness_score=flakiness_score,
                is_flaky=is_flaky,
                dominant_error_signature=dominant_sig,
                recommendation=recommendation,
            )
        )

    clusters.sort(key=lambda c: (-int(c.is_flaky), -c.flakiness_score, c.test_name))
    return clusters
