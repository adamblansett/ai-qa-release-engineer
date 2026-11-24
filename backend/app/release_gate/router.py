from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit.schemas import ApprovalRequestOut
from app.audit.service import create_approval_request, record_audit_event
from app.core.auth import Actor, get_current_actor, require_roles
from app.core.config import Settings, get_settings
from app.db.models import (
    ApprovalRequest,
    CiBuildRun,
    RegressionRun,
    ReleaseCandidate,
    SmokeProbeResult,
)
from app.db.session import get_db
from app.llm.router import LLMRouter, get_llm_router
from app.release_gate.evaluator import (
    evaluate_release_checklist,
    execute_smoke_probe,
    validate_probe_url,
)
from app.release_gate.schemas import (
    ReleaseCandidateCreateRequest,
    ReleaseCandidateOut,
    ReleaseEvaluateRequest,
    SmokeProbeBatchRequest,
)

router = APIRouter(prefix="/release-gate", tags=["release-gate"])


def _resolve_settings(request: Request) -> Settings:
    cfg = getattr(request.app.state, "settings", None)
    return cfg if isinstance(cfg, Settings) else get_settings()


async def _load_release(db: AsyncSession, release_id: str) -> ReleaseCandidate:
    stmt = (
        select(ReleaseCandidate)
        .options(selectinload(ReleaseCandidate.smoke_probes))
        .where(ReleaseCandidate.id == release_id)
    )
    release = (await db.execute(stmt)).scalar_one_or_none()
    if release is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release candidate '{release_id}' not found.",
        )
    return release


async def _refresh_readiness(
    db: AsyncSession,
    release: ReleaseCandidate,
    settings: Settings,
    llm_router: LLMRouter,
) -> None:
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
    llm_resp = await llm_router.generate(
        prompt=(
            f"Release {release.version_tag} ({release.service_name} -> {release.environment}) "
            f"readiness score {score}/100, decision={decision}."
        ),
        system_prompt="Provide concise deployment verification readiness summary.",
        task_type="release_gate",
    )

    release.readiness_score = score
    release.decision = decision
    release.checklist_json = checklist
    release.ai_readiness_brief = llm_resp.content
    if release.status not in {"approved", "rolled_back"}:
        release.status = "evaluating" if decision == "go" else "blocked"


@router.get("/releases", response_model=list[ReleaseCandidateOut])
async def list_releases(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[ReleaseCandidate]:
    """List release candidates with smoke probes and Go/No-Go checklist."""
    _ = actor
    stmt = (
        select(ReleaseCandidate)
        .options(selectinload(ReleaseCandidate.smoke_probes))
        .order_by(ReleaseCandidate.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


@router.get("/releases/{release_id}", response_model=ReleaseCandidateOut)
async def get_release(
    release_id: str,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> ReleaseCandidate:
    """Fetch a single release candidate and its smoke probe history."""
    _ = actor
    return await _load_release(db, release_id)


@router.post("/releases", response_model=ReleaseCandidateOut, status_code=status.HTTP_201_CREATED)
async def create_release_candidate(
    payload: ReleaseCandidateCreateRequest,
    request: Request,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> ReleaseCandidate:
    """Register a release candidate and evaluate initial Go/No-Go readiness."""
    settings = _resolve_settings(request)
    version_tag = payload.version_tag.strip()
    existing = (
        await db.execute(
            select(ReleaseCandidate).where(ReleaseCandidate.version_tag == version_tag)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Release version '{version_tag}' already exists.",
        )

    release = ReleaseCandidate(
        version_tag=version_tag,
        service_name=payload.service_name.strip(),
        environment=payload.environment.strip(),
        commit_sha=payload.commit_sha.strip(),
        previous_version_tag=payload.previous_version_tag.strip(),
        rollback_runbook_url=payload.rollback_runbook_url.strip(),
        rollback_verified=payload.rollback_verified,
        canary_error_rate_pct=payload.canary_error_rate_pct,
        canary_p95_latency_ms=payload.canary_p95_latency_ms,
        canary_traffic_pct=payload.canary_traffic_pct,
        regression_run_id=payload.regression_run_id,
        created_by=actor.email,
    )
    db.add(release)
    await db.flush()

    await _refresh_readiness(db, release, settings, llm_router)
    await record_audit_event(
        db,
        event_type="release.created",
        actor=actor,
        entity_type="release_candidate",
        entity_id=release.id,
        action="register_release",
        details={
            "version_tag": release.version_tag,
            "environment": release.environment,
            "decision": release.decision,
            "readiness_score": release.readiness_score,
        },
    )
    await db.commit()
    return await _load_release(db, release.id)


@router.post("/releases/{release_id}/probes", response_model=ReleaseCandidateOut)
async def run_smoke_probes(
    release_id: str,
    payload: SmokeProbeBatchRequest,
    request: Request,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> ReleaseCandidate:
    """Execute post-deploy smoke probes against a release candidate and re-evaluate gates."""
    settings = _resolve_settings(request)
    release = await _load_release(db, release_id)

    for probe in payload.probes:
        try:
            validate_probe_url(probe.target_url)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    passed_count = 0
    for probe in payload.probes:
        res = await execute_smoke_probe(probe)
        if res["passed"]:
            passed_count += 1
        db.add(
            SmokeProbeResult(
                release_id=release.id,
                probe_name=probe.probe_name.strip(),
                target_url=probe.target_url.strip(),
                http_method=probe.http_method,
                expected_status=probe.expected_status,
                actual_status=res["actual_status"],
                latency_ms=float(res["latency_ms"]),
                max_latency_ms=probe.max_latency_ms,
                expected_body_contains=probe.expected_body_contains,
                passed=bool(res["passed"]),
                mode=probe.mode,
                error_detail=str(res["error_detail"]),
            )
        )
    await db.flush()

    await _refresh_readiness(db, release, settings, llm_router)
    await record_audit_event(
        db,
        event_type="release.probes_executed",
        actor=actor,
        entity_type="release_candidate",
        entity_id=release.id,
        action="execute_smoke_probes",
        details={
            "version_tag": release.version_tag,
            "probes_total": len(payload.probes),
            "probes_passed": passed_count,
            "decision": release.decision,
        },
    )
    await db.commit()
    return await _load_release(db, release.id)


@router.post("/releases/{release_id}/evaluate", response_model=ReleaseCandidateOut)
async def evaluate_release(
    release_id: str,
    payload: ReleaseEvaluateRequest,
    request: Request,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> ReleaseCandidate:
    """Update canary/rollback telemetry and recompute the 6-gate Go/No-Go decision."""
    settings = _resolve_settings(request)
    release = await _load_release(db, release_id)

    if payload.canary_error_rate_pct is not None:
        release.canary_error_rate_pct = payload.canary_error_rate_pct
    if payload.canary_p95_latency_ms is not None:
        release.canary_p95_latency_ms = payload.canary_p95_latency_ms
    if payload.canary_traffic_pct is not None:
        release.canary_traffic_pct = payload.canary_traffic_pct
    if payload.rollback_verified is not None:
        release.rollback_verified = payload.rollback_verified
    if payload.rollback_runbook_url is not None:
        release.rollback_runbook_url = payload.rollback_runbook_url.strip()
    if payload.regression_run_id is not None:
        release.regression_run_id = payload.regression_run_id

    await _refresh_readiness(db, release, settings, llm_router)
    await record_audit_event(
        db,
        event_type="release.evaluated",
        actor=actor,
        entity_type="release_candidate",
        entity_id=release.id,
        action=f"evaluate_{release.decision}",
        details={
            "version_tag": release.version_tag,
            "readiness_score": release.readiness_score,
            "decision": release.decision,
        },
    )
    await db.commit()
    return await _load_release(db, release.id)


@router.post("/releases/{release_id}/request-promotion", response_model=ApprovalRequestOut)
async def request_release_promotion(
    release_id: str,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequest:
    """Submit a release candidate for HITL production promotion approval."""
    release = await _load_release(db, release_id)
    if release.approval_id:
        existing = await db.get(ApprovalRequest, release.approval_id)
        if existing is not None:
            return existing

    approval = await create_approval_request(
        db,
        entity_type="release_promotion",
        entity_id=release.id,
        action_requested=(
            f"Promote {release.service_name} {release.version_tag} to {release.environment}"
        ),
        summary=(
            f"Readiness score {release.readiness_score}/100 ({release.decision.upper()}). "
            f"Canary error rate {release.canary_error_rate_pct:.2f}%, "
            f"p95 latency {release.canary_p95_latency_ms:.1f}ms."
        ),
        risk_level="low" if release.decision == "go" else "high",
        requested_by=actor.email,
    )
    release.approval_id = approval.id
    release.status = "pending_approval"

    await record_audit_event(
        db,
        event_type="release.promotion_requested",
        actor=actor,
        entity_type="release_candidate",
        entity_id=release.id,
        action="request_promotion",
        details={
            "approval_id": approval.id,
            "version_tag": release.version_tag,
            "decision": release.decision,
        },
    )
    await db.commit()
    await db.refresh(approval)
    return approval


@router.post("/releases/{release_id}/request-rollback", response_model=ApprovalRequestOut)
async def request_release_rollback(
    release_id: str,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequest:
    """Create a HITL approval request to roll back a release to previous_version_tag."""
    release = await _load_release(db, release_id)
    if release.rollback_approval_id:
        existing = await db.get(ApprovalRequest, release.rollback_approval_id)
        if existing is not None:
            return existing

    target_prev = release.previous_version_tag or "previous-stable"
    approval = await create_approval_request(
        db,
        entity_type="rollback_execution",
        entity_id=release.id,
        action_requested=(
            f"Rollback {release.service_name} {release.version_tag} -> {target_prev}"
        ),
        summary=(
            f"Execute rollback for {release.version_tag} in {release.environment} "
            f"(canary error rate {release.canary_error_rate_pct:.2f}%, "
            f"decision {release.decision.upper()})."
        ),
        risk_level="high",
        requested_by=actor.email,
    )
    release.rollback_approval_id = approval.id

    await record_audit_event(
        db,
        event_type="release.rollback_requested",
        actor=actor,
        entity_type="release_candidate",
        entity_id=release.id,
        action="request_rollback",
        details={
            "approval_id": approval.id,
            "version_tag": release.version_tag,
            "target_version": target_prev,
        },
    )
    await db.commit()
    await db.refresh(approval)
    return approval
