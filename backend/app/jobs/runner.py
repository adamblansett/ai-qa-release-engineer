from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.ci_triage.embeddings import build_failure_embedding_text, generate_embedding
from app.core.auth import Actor
from app.core.config import Settings
from app.db.base import utcnow
from app.db.models import (
    BackgroundJob,
    CiBuildRun,
    RegressionBaseline,
    RegressionRun,
    ReleaseCandidate,
    SmokeProbeResult,
)
from app.llm.router import LLMRouter
from app.regression.engine import evaluate_regression_run
from app.release_gate.evaluator import evaluate_release_checklist, execute_smoke_probe
from app.release_gate.schemas import SmokeProbeInput

QUEUE_KEY = "qa:jobs:queue"


async def execute_job(
    db: AsyncSession,
    *,
    job: BackgroundJob,
    settings: Settings,
    llm_router: LLMRouter,
    actor: Actor,
) -> BackgroundJob:
    """Execute a queued or inline background QA/release job and persist its result."""
    job.status = "running"
    job.started_at = utcnow()
    await db.flush()

    try:
        if job.job_type == "embedding_reindex":
            runs = list((await db.execute(select(CiBuildRun))).scalars().all())
            reindexed = 0
            for run in runs:
                text = build_failure_embedding_text(
                    category=run.root_cause_category,
                    signature=run.failure_signature,
                    raw_log=run.raw_log,
                    job_name=run.job_name,
                )
                run.embedding_json = await generate_embedding(text, settings)
                reindexed += 1
            job.result_json = {"reindexed_runs": reindexed}

        elif job.job_type == "canary_smoke_sweep":
            release_id = str(job.payload_json.get("release_id") or "").strip()
            target_url = str(
                job.payload_json.get("target_url")
                or "https://canary.checkout.internal/api/v1/health/ready"
            )
            if not release_id:
                first_rel = (
                    await db.execute(
                        select(ReleaseCandidate)
                        .order_by(ReleaseCandidate.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if first_rel is None:
                    raise ValueError("No release candidate available for smoke sweep.")
                release = first_rel
            else:
                found = await db.get(ReleaseCandidate, release_id)
                if found is None:
                    raise ValueError(f"Release candidate '{release_id}' not found.")
                release = found

            probe_input = SmokeProbeInput(
                probe_name=str(job.payload_json.get("probe_name") or "scheduled-canary-sweep"),
                target_url=target_url,
                expected_status=int(job.payload_json.get("expected_status") or 200),
                max_latency_ms=float(job.payload_json.get("max_latency_ms") or 400.0),
                expected_body_contains=str(job.payload_json.get("expected_body_contains") or "ok"),
                mode="live_http"
                if str(job.payload_json.get("mode") or "simulated") == "live_http"
                else "simulated",
                simulated_status=int(job.payload_json.get("simulated_status") or 200),
                simulated_latency_ms=float(job.payload_json.get("simulated_latency_ms") or 35.0),
                simulated_body=str(job.payload_json.get("simulated_body") or '{"status":"ok"}'),
            )
            probe_res = await execute_smoke_probe(probe_input)
            db.add(
                SmokeProbeResult(
                    release_id=release.id,
                    probe_name=probe_input.probe_name,
                    target_url=probe_input.target_url,
                    http_method=probe_input.http_method,
                    expected_status=probe_input.expected_status,
                    actual_status=probe_res["actual_status"],
                    latency_ms=float(probe_res["latency_ms"]),
                    max_latency_ms=probe_input.max_latency_ms,
                    expected_body_contains=probe_input.expected_body_contains,
                    passed=bool(probe_res["passed"]),
                    mode=probe_input.mode,
                    error_detail=str(probe_res["error_detail"]),
                )
            )
            await db.flush()

            probes = list(
                (
                    await db.execute(
                        select(SmokeProbeResult).where(SmokeProbeResult.release_id == release.id)
                    )
                )
                .scalars()
                .all()
            )
            reg_run = (
                await db.get(RegressionRun, release.regression_run_id)
                if release.regression_run_id
                else None
            )
            blocking_ci = list(
                (
                    await db.execute(
                        select(CiBuildRun).where(
                            CiBuildRun.commit_sha == release.commit_sha,
                            CiBuildRun.status == "failed",
                        )
                    )
                )
                .scalars()
                .all()
            )
            score, decision, checklist = evaluate_release_checklist(
                release=release,
                probes=probes,
                regression_run=reg_run,
                blocking_ci_runs=blocking_ci,
                settings=settings,
            )
            release.readiness_score = score
            release.decision = decision
            release.checklist_json = checklist
            job.result_json = {
                "release_id": release.id,
                "version_tag": release.version_tag,
                "probe_passed": bool(probe_res["passed"]),
                "readiness_score": score,
                "decision": decision,
            }

        elif job.job_type == "regression_suite_run":
            suite_name = str(job.payload_json.get("suite_name") or "").strip()
            if not suite_name:
                first_bl = (
                    await db.execute(select(RegressionBaseline).limit(1))
                ).scalar_one_or_none()
                if first_bl is None:
                    raise ValueError("No regression baseline available.")
                baseline = first_bl
            else:
                found_bl = (
                    await db.execute(
                        select(RegressionBaseline).where(
                            RegressionBaseline.suite_name == suite_name
                        )
                    )
                ).scalar_one_or_none()
                if found_bl is None:
                    raise ValueError(f"Regression baseline '{suite_name}' not found.")
                baseline = found_bl

            raw_cand = job.payload_json.get("candidate_payload_json")
            candidate_payload: dict[str, Any] = (
                raw_cand if isinstance(raw_cand, dict) else baseline.baseline_payload_json
            )
            lat = float(job.payload_json.get("latency_p95_ms") or 140.0)
            ev = evaluate_regression_run(
                baseline_payload=baseline.baseline_payload_json,
                candidate_payload=candidate_payload,
                candidate_latency_p95_ms=lat,
                settings=settings,
            )
            llm_resp = await llm_router.generate(
                prompt=f"Background regression suite {baseline.suite_name}: {ev['status']}",
                task_type="regression_diff",
            )
            new_reg_run = RegressionRun(
                baseline_id=baseline.id,
                suite_name=baseline.suite_name,
                commit_sha=str(job.payload_json.get("commit_sha") or "scheduled-sweep"),
                branch=str(job.payload_json.get("branch") or "main"),
                gate_type=baseline.gate_type,
                status=str(ev["status"]),
                total_checks=int(ev["total_checks"]),
                passed_checks=int(ev["passed_checks"]),
                failed_checks=int(ev["failed_checks"]),
                latency_p95_ms=lat,
                latency_drift_pct=float(ev["latency_drift_pct"]),
                llm_eval_score=ev["llm_eval_score"],
                candidate_payload_json=candidate_payload,
                diff_report_json=dict(ev["diff_report"]),
                ai_summary=llm_resp.content,
                executed_by=actor.email,
            )
            db.add(new_reg_run)
            await db.flush()
            job.result_json = {
                "regression_run_id": new_reg_run.id,
                "suite_name": new_reg_run.suite_name,
                "status": new_reg_run.status,
                "passed_checks": new_reg_run.passed_checks,
                "total_checks": new_reg_run.total_checks,
            }
        else:
            raise ValueError(f"Unsupported job_type '{job.job_type}'.")

        job.status = "completed"
        job.completed_at = utcnow()
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.completed_at = utcnow()

    await record_audit_event(
        db,
        event_type="job.executed",
        actor=actor,
        entity_type="background_job",
        entity_id=job.id,
        action=f"{job.job_type}_{job.status}",
        details={"job_type": job.job_type, "status": job.status, "result": job.result_json},
    )
    await db.commit()
    await db.refresh(job)
    return job
