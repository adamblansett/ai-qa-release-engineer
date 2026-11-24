from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import verify_audit_chain
from app.ci_triage.analyzer import compute_flaky_clusters
from app.core.auth import Actor, get_current_actor
from app.core.config import Settings, get_settings
from app.db.models import (
    ApprovalRequest,
    AuditEvent,
    CiBuildRun,
    GeneratedTestCase,
    RegressionBaseline,
    RegressionRun,
    ReleaseCandidate,
    TestExecutionRecord,
    TestSuite,
    WorkflowAudit,
)
from app.db.session import get_db

router = APIRouter(prefix="/overview", tags=["overview"])


class OverviewSummary(BaseModel):
    test_suites_count: int
    generated_cases_count: int
    ci_runs_count: int
    ci_failed_runs_count: int
    flaky_tests_count: int
    workflow_audits_count: int
    regression_baselines_count: int
    regression_runs_count: int
    regression_failed_runs_count: int
    release_candidates_count: int
    go_releases_count: int
    blocked_releases_count: int
    pending_approvals_count: int
    audit_events_count: int
    audit_chain_valid: bool
    llm_provider: str
    pii_redaction_enabled: bool


@router.get("", response_model=OverviewSummary)
async def get_overview(
    request: Request,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> OverviewSummary:
    """Return executive QA and release readiness KPIs across all four platform modules."""
    _ = actor
    cfg = getattr(request.app.state, "settings", None)
    settings = cfg if isinstance(cfg, Settings) else get_settings()

    test_suites_count = int(
        (await db.execute(select(func.count()).select_from(TestSuite))).scalar_one()
    )
    generated_cases_count = int(
        (await db.execute(select(func.count()).select_from(GeneratedTestCase))).scalar_one()
    )
    ci_runs_count = int(
        (await db.execute(select(func.count()).select_from(CiBuildRun))).scalar_one()
    )
    ci_failed_runs_count = int(
        (
            await db.execute(
                select(func.count()).select_from(CiBuildRun).where(CiBuildRun.status == "failed")
            )
        ).scalar_one()
    )
    records = list(
        (
            await db.execute(
                select(TestExecutionRecord).order_by(TestExecutionRecord.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    flaky_clusters = compute_flaky_clusters(records, settings)
    flaky_tests_count = sum(1 for c in flaky_clusters if c.is_flaky)

    workflow_audits_count = int(
        (await db.execute(select(func.count()).select_from(WorkflowAudit))).scalar_one()
    )
    regression_baselines_count = int(
        (await db.execute(select(func.count()).select_from(RegressionBaseline))).scalar_one()
    )
    regression_runs_count = int(
        (await db.execute(select(func.count()).select_from(RegressionRun))).scalar_one()
    )
    regression_failed_runs_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(RegressionRun)
                .where(RegressionRun.status == "failed")
            )
        ).scalar_one()
    )
    release_candidates_count = int(
        (await db.execute(select(func.count()).select_from(ReleaseCandidate))).scalar_one()
    )
    go_releases_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ReleaseCandidate)
                .where(ReleaseCandidate.decision == "go")
            )
        ).scalar_one()
    )
    blocked_releases_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ReleaseCandidate)
                .where(ReleaseCandidate.decision == "no_go")
            )
        ).scalar_one()
    )
    pending_approvals_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ApprovalRequest)
                .where(ApprovalRequest.status == "pending")
            )
        ).scalar_one()
    )
    audit_events_count = int(
        (await db.execute(select(func.count()).select_from(AuditEvent))).scalar_one()
    )
    chain_verify = await verify_audit_chain(db)

    return OverviewSummary(
        test_suites_count=test_suites_count,
        generated_cases_count=generated_cases_count,
        ci_runs_count=ci_runs_count,
        ci_failed_runs_count=ci_failed_runs_count,
        flaky_tests_count=flaky_tests_count,
        workflow_audits_count=workflow_audits_count,
        regression_baselines_count=regression_baselines_count,
        regression_runs_count=regression_runs_count,
        regression_failed_runs_count=regression_failed_runs_count,
        release_candidates_count=release_candidates_count,
        go_releases_count=go_releases_count,
        blocked_releases_count=blocked_releases_count,
        pending_approvals_count=pending_approvals_count,
        audit_events_count=audit_events_count,
        audit_chain_valid=chain_verify.valid,
        llm_provider=settings.llm_default_provider,
        pii_redaction_enabled=settings.llm_redact_pii_for_cloud,
    )
