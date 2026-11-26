import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Literal

from app.ci_triage.schemas import TestExecutionInput

_XXE_FORBIDDEN_RE = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


def parse_junit_xml(xml_text: str) -> tuple[list[TestExecutionInput], str]:
    """Parse JUnit XML reports with strict XXE/DOCTYPE rejection."""
    if _XXE_FORBIDDEN_RE.search(xml_text):
        raise ValueError("XML DOCTYPE/ENTITY declarations are forbidden by XXE policy.")

    root = ET.fromstring(xml_text.strip())
    records: list[TestExecutionInput] = []
    failure_lines: list[str] = []

    for tc in root.iter("testcase"):
        classname = str(tc.attrib.get("classname") or "").strip()
        name = str(tc.attrib.get("name") or "unnamed_test").strip()
        full_name = f"{classname}::{name}" if classname else name
        time_sec = float(tc.attrib.get("time") or 0.0)
        duration_ms = round(max(0.0, time_sec * 1000.0), 2)

        failure_el = tc.find("failure")
        error_el = tc.find("error")
        skipped_el = tc.find("skipped")

        if failure_el is not None or error_el is not None:
            bad_el = failure_el if failure_el is not None else error_el
            msg = ""
            if bad_el is not None:
                msg = str(bad_el.attrib.get("message") or (bad_el.text or "")).strip()
            records.append(
                TestExecutionInput(
                    test_name=full_name[:300],
                    suite_name=classname[:160] or "junit",
                    outcome="failed",
                    duration_ms=duration_ms,
                    error_message=msg[:4000],
                )
            )
            failure_lines.append(f"FAILED {full_name} - {msg or 'JUnit failure'}")
        elif skipped_el is not None:
            records.append(
                TestExecutionInput(
                    test_name=full_name[:300],
                    suite_name=classname[:160] or "junit",
                    outcome="skipped",
                    duration_ms=duration_ms,
                )
            )
        else:
            records.append(
                TestExecutionInput(
                    test_name=full_name[:300],
                    suite_name=classname[:160] or "junit",
                    outcome="passed",
                    duration_ms=duration_ms,
                )
            )

    if not records:
        raise ValueError("No <testcase> entries found in JUnit XML report.")

    summary_log = (
        "\n".join(failure_lines)
        if failure_lines
        else f"{len(records)} passed in JUnit XML report"
    )
    return records, summary_log


def _walk_playwright_suite(
    suite: dict[str, Any],
    suite_title: str,
    records: list[TestExecutionInput],
    failure_lines: list[str],
) -> None:
    current_title = str(suite.get("title") or suite_title or "playwright").strip()
    specs = suite.get("specs")
    if isinstance(specs, list):
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            spec_title = str(spec.get("title") or "spec").strip()
            tests = spec.get("tests")
            if not isinstance(tests, list):
                continue
            for test_obj in tests:
                if not isinstance(test_obj, dict):
                    continue
                results = test_obj.get("results")
                if not isinstance(results, list) or not results:
                    continue
                last_res = results[-1] if isinstance(results[-1], dict) else {}
                raw_status = str(last_res.get("status") or "passed").lower()
                outcome: Literal["passed", "failed", "skipped"] = (
                    "passed"
                    if raw_status == "passed"
                    else ("skipped" if raw_status == "skipped" else "failed")
                )
                duration_ms = float(last_res.get("duration") or 0.0)
                err_obj = last_res.get("error")
                err_msg = (
                    str(err_obj.get("message") or "")
                    if isinstance(err_obj, dict)
                    else ""
                )
                test_name = f"{current_title} › {spec_title}"
                records.append(
                    TestExecutionInput(
                        test_name=test_name[:300],
                        suite_name=current_title[:160],
                        outcome=outcome,
                        duration_ms=round(max(0.0, duration_ms), 2),
                        error_message=err_msg[:4000],
                    )
                )
                if outcome == "failed":
                    failure_lines.append(
                        f"1) [chromium] › {test_name}\n{err_msg or 'Playwright test failed'}"
                    )

    nested_suites = suite.get("suites")
    if isinstance(nested_suites, list):
        for child in nested_suites:
            if isinstance(child, dict):
                _walk_playwright_suite(child, current_title, records, failure_lines)


def parse_playwright_json(json_text: str) -> tuple[list[TestExecutionInput], str]:
    """Parse Playwright JSON reporter output into normalized TestExecutionInput records."""
    parsed = json.loads(json_text)
    if not isinstance(parsed, dict):
        raise ValueError("Playwright JSON report must be a JSON object.")

    records: list[TestExecutionInput] = []
    failure_lines: list[str] = []
    suites = parsed.get("suites")
    if isinstance(suites, list):
        for suite in suites:
            if isinstance(suite, dict):
                _walk_playwright_suite(suite, "playwright", records, failure_lines)

    if not records:
        raise ValueError("No test results found in Playwright JSON report.")

    summary_log = (
        "\n".join(failure_lines)
        if failure_lines
        else f"{len(records)} passed in Playwright JSON report"
    )
    return records, summary_log
