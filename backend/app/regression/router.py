from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.schemas import ApprovalRequestOut
from app.audit.service import create_approval_request, record_audit_event
from app.core.auth import Actor, get_current_actor, require_roles
from app.core.config import Settings, get_settings
from app.db.base import utcnow
from app.db.models import ApprovalRequest, RegressionBaseline, RegressionRun
from app.db.session import get_db
from app.llm.router import LLMRouter, get_llm_router
from app.regression.engine import evaluate_regression_run
from app.regression.schemas import (
    RegressionBaselineCreateRequest,
    RegressionBaselineOut,
    RegressionRunOut,
    RegressionRunRequest,
)

router = APIRouter(prefix="/regression", tags=["regression"])


def _resolve_settings(request: Request) -> Settings:
    cfg = getattr(request.app.state, "settings", None)
    return cfg if isinstance(cfg, Settings) else get_settings()


@router.get("/baselines", response_model=list[RegressionBaselineOut])
async def list_baselines(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[RegressionBaseline]:
    """List deterministic contract, snapshot, and LLM-eval baselines."""
    _ = actor
    stmt = select(RegressionBaseline).order_by(RegressionBaseline.suite_name.asc())
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/baselines",
    response_model=RegressionBaselineOut,
    status_code=status.HTTP_201_CREATED,
)
async def upsert_baseline(
    payload: RegressionBaselineCreateRequest,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> RegressionBaseline:
    """Create or update a regression baseline for a test suite."""
    suite_name = payload.suite_name.strip()
    existing = (
        await db.execute(
            select(RegressionBaseline).where(RegressionBaseline.suite_name == suite_name)
        )
    ).scalar_one_or_none()

    if existing is None:
        baseline = RegressionBaseline(
            suite_name=suite_name,
            service_name=payload.service_name.strip(),
            gate_type=payload.gate_type,
            version=1,
            baseline_payload_json=payload.baseline_payload_json,
            updated_by=actor.email,
        )
        db.add(baseline)
        await db.flush()
        action = "create_baseline"
    else:
        existing.service_name = payload.service_name.strip()
        existing.gate_type = payload.gate_type
        existing.version += 1
        existing.baseline_payload_json = payload.baseline_payload_json
        existing.updated_by = actor.email
        existing.updated_at = utcnow()
        baseline = existing
        action = "update_baseline"

    await record_audit_event(
        db,
        event_type="regression.baseline_saved",
        actor=actor,
        entity_type="regression_baseline",
        entity_id=baseline.id,
        action=action,
        details={
            "suite_name": baseline.suite_name,
            "version": baseline.version,
            "gate_type": baseline.gate_type,
        },
    )
    await db.commit()
    await db.refresh(baseline)
    return baseline


@router.get("/runs", response_model=list[RegressionRunOut])
async def list_regression_runs(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[RegressionRun]:
    """List regression gate runs newest first."""
    _ = actor
    stmt = select(RegressionRun).order_by(RegressionRun.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())


@router.get("/runs/{run_id}", response_model=RegressionRunOut)
async def get_regression_run(
    run_id: str,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> RegressionRun:
    """Retrieve a single regression run and its full diff report."""
    _ = actor
    run = await db.get(RegressionRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Regression run '{run_id}' not found.",
        )
    return run


@router.post("/runs", response_model=RegressionRunOut, status_code=status.HTTP_201_CREATED)
async def execute_regression_run(
    payload: RegressionRunRequest,
    request: Request,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> RegressionRun:
    """Execute contract, snapshot, and LLM-eval checks against the active baseline."""
    settings = _resolve_settings(request)
    suite_name = payload.suite_name.strip()
    baseline = (
        await db.execute(
            select(RegressionBaseline).where(RegressionBaseline.suite_name == suite_name)
        )
    ).scalar_one_or_none()
    if baseline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Regression baseline for suite '{suite_name}' not found.",
        )

    evaluation = evaluate_regression_run(
        baseline_payload=baseline.baseline_payload_json,
        candidate_payload=payload.candidate_payload_json,
        candidate_latency_p95_ms=payload.latency_p95_ms,
        settings=settings,
    )

    llm_resp = await llm_router.generate(
        prompt=(
            f"Suite {suite_name} v{baseline.version} on {payload.branch} ({payload.commit_sha}): "
            f"status={evaluation['status']}, passed={evaluation['passed_checks']}/"
            f"{evaluation['total_checks']}, drift={evaluation['latency_drift_pct']}%."
        ),
        system_prompt="Summarize regression diff findings concisely.",
        task_type="regression_diff",
    )

    run = RegressionRun(
        baseline_id=baseline.id,
        suite_name=baseline.suite_name,
        commit_sha=payload.commit_sha.strip(),
        branch=payload.branch.strip(),
        gate_type=baseline.gate_type,
        status=str(evaluation["status"]),
        total_checks=int(evaluation["total_checks"]),
        passed_checks=int(evaluation["passed_checks"]),
        failed_checks=int(evaluation["failed_checks"]),
        latency_p95_ms=payload.latency_p95_ms,
        latency_drift_pct=float(evaluation["latency_drift_pct"]),
        llm_eval_score=evaluation["llm_eval_score"],
        candidate_payload_json=payload.candidate_payload_json,
        diff_report_json=dict(evaluation["diff_report"]),
        ai_summary=llm_resp.content,
        executed_by=actor.email,
    )
    db.add(run)
    await db.flush()

    await record_audit_event(
        db,
        event_type="regression.executed",
        actor=actor,
        entity_type="regression_run",
        entity_id=run.id,
        action=f"run_{run.status}",
        details={
            "suite_name": run.suite_name,
            "commit_sha": run.commit_sha,
            "total_checks": run.total_checks,
            "failed_checks": run.failed_checks,
            "latency_drift_pct": run.latency_drift_pct,
        },
    )
    await db.commit()
    await db.refresh(run)
    return run


@router.post("/runs/{run_id}/propose-baseline", response_model=ApprovalRequestOut)
async def propose_baseline_promotion(
    run_id: str,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequest:
    """Create a human-in-the-loop approval request to promote candidate outputs as new baseline."""
    run = await db.get(RegressionRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Regression run '{run_id}' not found.",
        )
    if run.promotion_approval_id:
        existing = await db.get(ApprovalRequest, run.promotion_approval_id)
        if existing is not None:
            return existing

    approval = await create_approval_request(
        db,
        entity_type="baseline_promotion",
        entity_id=run.id,
        action_requested=f"Promote regression baseline for '{run.suite_name}' ({run.commit_sha})",
        summary=(
            f"Promote candidate snapshots/contracts from commit {run.commit_sha} "
            f"({run.failed_checks} diff(s)) to active baseline."
        ),
        risk_level="medium" if run.failed_checks > 0 else "low",
        requested_by=actor.email,
    )
    run.promotion_approval_id = approval.id

    await record_audit_event(
        db,
        event_type="regression.baseline_promotion_proposed",
        actor=actor,
        entity_type="regression_run",
        entity_id=run.id,
        action="propose_baseline_promotion",
        details={"approval_id": approval.id, "suite_name": run.suite_name},
    )
    await db.commit()
    await db.refresh(approval)
    return approval
