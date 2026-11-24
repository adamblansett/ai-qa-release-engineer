from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.ci_triage.analyzer import (
    classify_root_cause,
    compute_flaky_clusters,
    normalize_signature,
    parse_ci_log,
)
from app.ci_triage.schemas import (
    CiBuildRunOut,
    CiLogAnalyzeRequest,
    FlakyClusterOut,
    WorkflowAuditOut,
    WorkflowAuditRequest,
)
from app.ci_triage.workflow_validator import validate_workflow_yaml
from app.core.auth import Actor, get_current_actor, require_roles
from app.core.config import Settings, get_settings
from app.db.models import CiBuildRun, TestExecutionRecord, WorkflowAudit
from app.db.session import get_db
from app.llm.router import LLMRouter, get_llm_router

router = APIRouter(prefix="/ci-triage", tags=["ci-triage"])


def _resolve_settings(request: Request) -> Settings:
    cfg = getattr(request.app.state, "settings", None)
    return cfg if isinstance(cfg, Settings) else get_settings()


@router.get("/runs", response_model=list[CiBuildRunOut])
async def list_ci_runs(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[CiBuildRun]:
    """List analyzed CI build runs newest first."""
    _ = actor
    stmt = select(CiBuildRun).order_by(CiBuildRun.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())


@router.post("/analyze", response_model=CiBuildRunOut, status_code=status.HTTP_201_CREATED)
async def analyze_ci_run(
    payload: CiLogAnalyzeRequest,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> CiBuildRun:
    """Parse CI build logs, classify root cause, and persist test execution outcomes."""
    extracted_errors, parsed_tests = parse_ci_log(payload.raw_log)
    resolved_status, category, signature, confidence, remediation = classify_root_cause(
        raw_log=payload.raw_log,
        status_hint=payload.status,
        extracted_errors=extracted_errors,
    )

    llm_resp = await llm_router.generate(
        prompt=(
            f"Pipeline {payload.pipeline_name} job {payload.job_name} on {payload.branch} "
            f"({payload.commit_sha}): status={resolved_status}, category={category}, "
            f"signature={signature}."
        ),
        system_prompt="Provide concise CI triage guidance.",
        task_type="ci_triage",
    )

    run = CiBuildRun(
        pipeline_name=payload.pipeline_name.strip(),
        branch=payload.branch.strip(),
        commit_sha=payload.commit_sha.strip(),
        job_name=payload.job_name.strip(),
        status=resolved_status,
        duration_seconds=payload.duration_seconds,
        raw_log=payload.raw_log,
        root_cause_category=category,
        failure_signature=signature,
        confidence=confidence,
        remediation_summary=remediation,
        ai_explanation=llm_resp.content,
        extracted_errors_json=extracted_errors,
    )
    db.add(run)
    await db.flush()

    records_to_save = payload.test_records if payload.test_records else parsed_tests
    for rec in records_to_save:
        err_sig = (
            normalize_signature(rec.error_message or signature)
            if rec.outcome == "failed"
            else ""
        )
        db.add(
            TestExecutionRecord(
                build_run_id=run.id,
                test_name=rec.test_name.strip(),
                suite_name=rec.suite_name.strip(),
                outcome=rec.outcome,
                duration_ms=rec.duration_ms,
                error_signature=err_sig,
                error_message=rec.error_message,
            )
        )

    await record_audit_event(
        db,
        event_type="ci.analyzed",
        actor=actor,
        entity_type="ci_build_run",
        entity_id=run.id,
        action=f"analyze_{resolved_status}",
        details={
            "pipeline_name": run.pipeline_name,
            "commit_sha": run.commit_sha,
            "root_cause_category": category,
            "record_count": len(records_to_save),
        },
    )
    await db.commit()
    await db.refresh(run)
    return run


@router.get("/flaky-clusters", response_model=list[FlakyClusterOut])
async def list_flaky_clusters(
    request: Request,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[FlakyClusterOut]:
    """Compute flaky-test clusters across historical test execution records."""
    _ = actor
    settings = _resolve_settings(request)
    stmt = select(TestExecutionRecord).order_by(TestExecutionRecord.created_at.asc())
    records = list((await db.execute(stmt)).scalars().all())
    return compute_flaky_clusters(records, settings)


@router.get("/workflow-audits", response_model=list[WorkflowAuditOut])
async def list_workflow_audits(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowAudit]:
    """List GitHub Actions workflow security & reliability validation audits."""
    _ = actor
    stmt = select(WorkflowAudit).order_by(WorkflowAudit.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/workflow-audits",
    response_model=WorkflowAuditOut,
    status_code=status.HTTP_201_CREATED,
)
async def audit_workflow_yaml(
    payload: WorkflowAuditRequest,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> WorkflowAudit:
    """Validate a GitHub Actions YAML workflow for permissions, timeouts, pinning, and leaks."""
    try:
        passed, score, findings = validate_workflow_yaml(payload.workflow_yaml)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid workflow YAML: {exc}",
        ) from exc

    audit = WorkflowAudit(
        workflow_name=payload.workflow_name.strip(),
        filename=payload.filename.strip(),
        workflow_yaml=payload.workflow_yaml,
        passed=passed,
        score=score,
        findings_json=findings,
    )
    db.add(audit)
    await db.flush()

    await record_audit_event(
        db,
        event_type="ci.workflow_audited",
        actor=actor,
        entity_type="workflow_audit",
        entity_id=audit.id,
        action="passed" if passed else "failed",
        details={
            "workflow_name": audit.workflow_name,
            "score": score,
            "finding_count": len(findings),
        },
    )
    await db.commit()
    await db.refresh(audit)
    return audit
