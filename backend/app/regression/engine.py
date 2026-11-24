import json
import re
from typing import Any

from app.core.config import Settings
from app.llm.pii import redact_pii

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _token_f1(prediction: str, reference: str) -> float:
    pred_tokens = _tokenize(prediction)
    ref_tokens = _tokenize(reference)
    if not pred_tokens or not ref_tokens:
        return 0.0
    pred_counts: dict[str, int] = {}
    for t in pred_tokens:
        pred_counts[t] = pred_counts.get(t, 0) + 1
    overlap = 0
    for t in ref_tokens:
        if pred_counts.get(t, 0) > 0:
            overlap += 1
            pred_counts[t] -= 1
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_tokens)
    recall = overlap / len(ref_tokens)
    return round((2 * precision * recall) / (precision + recall), 4)


def evaluate_contract_diff(
    baseline_contracts: dict[str, Any],
    candidate_contracts: dict[str, Any],
) -> tuple[int, int, int, dict[str, Any]]:
    """Compare endpoint contracts; flag removed endpoints, status shifts, and schema breaks."""
    breaking: list[dict[str, Any]] = []
    additive: list[dict[str, Any]] = []
    total = 0
    passed = 0
    failed = 0

    for endpoint, base_spec in baseline_contracts.items():
        if not isinstance(base_spec, dict):
            continue
        total += 1
        cand_spec = candidate_contracts.get(endpoint)
        if not isinstance(cand_spec, dict):
            failed += 1
            breaking.append(
                {
                    "endpoint": endpoint,
                    "issue": "endpoint_removed",
                    "detail": f"Endpoint '{endpoint}' missing from candidate contracts.",
                }
            )
            continue

        endpoint_broken = False
        base_status = base_spec.get("status")
        cand_status = cand_spec.get("status")
        if base_status is not None and cand_status != base_status:
            endpoint_broken = True
            breaking.append(
                {
                    "endpoint": endpoint,
                    "issue": "status_changed",
                    "expected": base_status,
                    "actual": cand_status,
                }
            )

        base_req = set(str(x) for x in (base_spec.get("required_fields") or []))
        cand_req = set(str(x) for x in (cand_spec.get("required_fields") or []))
        missing_req = sorted(base_req - cand_req)
        if missing_req:
            endpoint_broken = True
            breaking.append(
                {
                    "endpoint": endpoint,
                    "issue": "required_fields_removed",
                    "fields": missing_req,
                }
            )

        raw_base_types = base_spec.get("field_types")
        base_types: dict[str, Any] = raw_base_types if isinstance(raw_base_types, dict) else {}
        raw_cand_types = cand_spec.get("field_types")
        cand_types: dict[str, Any] = raw_cand_types if isinstance(raw_cand_types, dict) else {}
        for field, expected_type in base_types.items():
            actual_type = cand_types.get(field)
            if actual_type is None:
                endpoint_broken = True
                breaking.append(
                    {
                        "endpoint": endpoint,
                        "issue": "field_removed",
                        "field": field,
                    }
                )
            elif actual_type != expected_type:
                endpoint_broken = True
                breaking.append(
                    {
                        "endpoint": endpoint,
                        "issue": "field_type_changed",
                        "field": field,
                        "expected": expected_type,
                        "actual": actual_type,
                    }
                )

        new_fields = sorted(set(cand_types.keys()) - set(base_types.keys()))
        if new_fields:
            additive.append({"endpoint": endpoint, "added_fields": new_fields})

        if endpoint_broken:
            failed += 1
        else:
            passed += 1

    for endpoint in candidate_contracts:
        if endpoint not in baseline_contracts:
            additive.append({"endpoint": endpoint, "issue": "endpoint_added"})

    return total, passed, failed, {"breaking": breaking, "additive": additive}


def _diff_json_nodes(
    expected: Any,
    actual: Any,
    path: str,
    diffs: list[dict[str, Any]],
) -> None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        keys = sorted(set(expected.keys()) | set(actual.keys()))
        for k in keys:
            sub_path = f"{path}.{k}"
            if k not in expected:
                diffs.append({"path": sub_path, "change": "added", "actual": actual[k]})
            elif k not in actual:
                diffs.append({"path": sub_path, "change": "removed", "expected": expected[k]})
            else:
                _diff_json_nodes(expected[k], actual[k], sub_path, diffs)
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            diffs.append(
                {
                    "path": path,
                    "change": "array_length_changed",
                    "expected": len(expected),
                    "actual": len(actual),
                }
            )
            return
        for idx, (e_item, a_item) in enumerate(zip(expected, actual, strict=True)):
            _diff_json_nodes(e_item, a_item, f"{path}[{idx}]", diffs)
    elif expected != actual:
        diffs.append({"path": path, "change": "changed", "expected": expected, "actual": actual})


def evaluate_snapshot_diff(
    baseline_snapshots: dict[str, Any],
    candidate_snapshots: dict[str, Any],
) -> tuple[int, int, int, list[dict[str, Any]]]:
    """Perform recursive JSON snapshot diffing across named snapshot keys."""
    all_diffs: list[dict[str, Any]] = []
    total = 0
    passed = 0
    failed = 0

    for snap_key, expected_val in baseline_snapshots.items():
        total += 1
        if snap_key not in candidate_snapshots:
            failed += 1
            all_diffs.append(
                {
                    "snapshot": snap_key,
                    "path": "$",
                    "change": "removed",
                    "expected": expected_val,
                }
            )
            continue
        snap_diffs: list[dict[str, Any]] = []
        _diff_json_nodes(expected_val, candidate_snapshots[snap_key], "$", snap_diffs)
        if snap_diffs:
            failed += 1
            for d in snap_diffs:
                all_diffs.append({"snapshot": snap_key, **d})
        else:
            passed += 1

    return total, passed, failed, all_diffs


def evaluate_llm_eval(
    baseline_evals: list[dict[str, Any]],
    candidate_outputs: dict[str, Any],
    min_score: float,
) -> tuple[int, int, int, float | None, list[dict[str, Any]]]:
    """Score deterministic LLM evaluation rubrics (keywords, F1 overlap, JSON, PII leak)."""
    if not baseline_evals:
        return 0, 0, 0, None, []

    results: list[dict[str, Any]] = []
    scores: list[float] = []
    passed = 0
    failed = 0

    for case in baseline_evals:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("id") or f"eval_{len(results) + 1}")
        raw_cand = candidate_outputs.get(case_id)
        output_text = (
            str(raw_cand.get("output", ""))
            if isinstance(raw_cand, dict)
            else str(raw_cand or "")
        )
        lowered = output_text.lower()

        required_kw = [str(k) for k in (case.get("required_keywords") or [])]
        forbidden = [str(k) for k in (case.get("forbidden_terms") or [])]
        reference = str(case.get("reference_answer") or "")
        require_json = bool(case.get("require_json", False))
        baseline_case_score = float(case.get("baseline_score", min_score))

        pii_check = redact_pii(output_text)
        forbidden_hit = [term for term in forbidden if term.lower() in lowered]
        json_ok = True
        if require_json:
            try:
                json.loads(output_text)
            except Exception:
                json_ok = False

        if pii_check.total_redactions > 0 or forbidden_hit:
            case_score = 0.0
            reason = (
                "pii_leak_detected" if pii_check.total_redactions > 0 else "forbidden_term_present"
            )
            case_passed = False
        else:
            if required_kw:
                hits = sum(1 for kw in required_kw if kw.lower() in lowered)
                kw_recall = hits / len(required_kw)
            else:
                kw_recall = 1.0 if output_text.strip() else 0.0

            if reference.strip():
                f1 = _token_f1(output_text, reference)
                case_score = round(0.65 * kw_recall + 0.35 * f1, 4) if required_kw else f1
            else:
                case_score = round(kw_recall, 4)

            if require_json and not json_ok:
                case_score = min(case_score, 0.25)

            drop_exceeded = (baseline_case_score - case_score) > 0.05
            case_passed = json_ok and case_score >= min_score and not drop_exceeded
            if not json_ok:
                reason = "invalid_json_output"
            elif case_score < min_score:
                reason = "below_min_eval_score"
            elif drop_exceeded:
                reason = "regression_vs_baseline"
            else:
                reason = "ok"

        scores.append(case_score)
        if case_passed:
            passed += 1
        else:
            failed += 1
        results.append(
            {
                "id": case_id,
                "score": case_score,
                "baseline_score": baseline_case_score,
                "passed": case_passed,
                "reason": reason,
                "forbidden_hits": forbidden_hit,
                "pii_redactions": pii_check.total_redactions,
            }
        )

    avg_score = round(sum(scores) / len(scores), 4) if scores else None
    return len(results), passed, failed, avg_score, results


def evaluate_regression_run(
    *,
    baseline_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    candidate_latency_p95_ms: float,
    settings: Settings,
) -> dict[str, Any]:
    """Run all configured regression gates and compute latency drift and status."""
    raw_base_contracts = baseline_payload.get("contracts")
    base_contracts: dict[str, Any] = (
        raw_base_contracts if isinstance(raw_base_contracts, dict) else {}
    )
    raw_cand_contracts = candidate_payload.get("contracts")
    cand_contracts: dict[str, Any] = (
        raw_cand_contracts if isinstance(raw_cand_contracts, dict) else {}
    )
    c_tot, c_pass, c_fail, c_diff = evaluate_contract_diff(base_contracts, cand_contracts)

    raw_base_snaps = baseline_payload.get("snapshots")
    base_snaps: dict[str, Any] = raw_base_snaps if isinstance(raw_base_snaps, dict) else {}
    raw_cand_snaps = candidate_payload.get("snapshots")
    cand_snaps: dict[str, Any] = raw_cand_snaps if isinstance(raw_cand_snaps, dict) else {}
    s_tot, s_pass, s_fail, s_diff = evaluate_snapshot_diff(base_snaps, cand_snaps)

    raw_base_evals = baseline_payload.get("llm_evals")
    base_evals: list[dict[str, Any]] = (
        raw_base_evals if isinstance(raw_base_evals, list) else []
    )
    raw_cand_evals = candidate_payload.get("llm_eval_outputs")
    cand_evals: dict[str, Any] = raw_cand_evals if isinstance(raw_cand_evals, dict) else {}
    e_tot, e_pass, e_fail, avg_eval_score, e_results = evaluate_llm_eval(
        base_evals, cand_evals, settings.llm_eval_min_score
    )

    total_checks = c_tot + s_tot + e_tot
    passed_checks = c_pass + s_pass + e_pass
    failed_checks = c_fail + s_fail + e_fail

    base_latency = float(baseline_payload.get("latency_p95_ms") or 0.0)
    drift_pct = 0.0
    if base_latency > 0.0 and candidate_latency_p95_ms > 0.0:
        drift_pct = round(((candidate_latency_p95_ms - base_latency) / base_latency) * 100.0, 2)

    latency_warning = drift_pct > settings.regression_max_latency_drift_pct
    latency_failed = drift_pct > (settings.regression_max_latency_drift_pct * 2.0)

    if failed_checks > 0 or latency_failed:
        status = "failed"
    elif latency_warning:
        status = "warning"
    else:
        status = "passed"

    return {
        "status": status,
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "latency_drift_pct": drift_pct,
        "llm_eval_score": avg_eval_score,
        "diff_report": {
            "contract": c_diff,
            "snapshot": s_diff,
            "llm_eval": e_results,
            "latency": {
                "baseline_p95_ms": base_latency,
                "candidate_p95_ms": candidate_latency_p95_ms,
                "drift_pct": drift_pct,
                "warning": latency_warning,
                "failed": latency_failed,
            },
        },
    }
