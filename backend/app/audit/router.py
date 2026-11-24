from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.schemas import (
    ApprovalDecisionRequest,
    ApprovalRequestOut,
    AuditChainVerifyOut,
    AuditEventOut,
    PiiRedactRequest,
)
from app.audit.service import decide_approval, verify_audit_chain
from app.core.auth import Actor, get_current_actor, require_roles
from app.db.models import ApprovalRequest, AuditEvent
from app.db.session import get_db
from app.llm.pii import RedactionResult, redact_pii

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/approvals", response_model=list[ApprovalRequestOut])
async def list_approvals(
    status_filter: str | None = Query(default=None, alias="status"),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalRequest]:
    """List human-in-the-loop approval requests."""
    _ = actor
    stmt = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())
    if status_filter:
        stmt = stmt.where(ApprovalRequest.status == status_filter.strip().lower())
    return list((await db.execute(stmt)).scalars().all())


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalRequestOut)
async def decide_approval_endpoint(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    actor: Actor = Depends(require_roles("release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequest:
    """Approve or reject a pending HITL gate (requires release_manager or admin)."""
    return await decide_approval(
        db,
        approval_id=approval_id,
        decision=payload.decision,
        notes=payload.notes,
        actor=actor,
    )


@router.get("/events", response_model=list[AuditEventOut])
async def list_audit_events(
    limit: int = Query(default=100, ge=1, le=500),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[AuditEvent]:
    """Return hash-chained governance audit events newest first."""
    _ = actor
    stmt = select(AuditEvent).order_by(AuditEvent.sequence_no.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/events/verify", response_model=AuditChainVerifyOut)
async def verify_audit_trail(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> AuditChainVerifyOut:
    """Verify SHA-256 hash chain integrity across all audit events."""
    _ = actor
    return await verify_audit_chain(db)


@router.post("/pii/redact", response_model=RedactionResult)
async def test_pii_redaction(
    payload: PiiRedactRequest,
    actor: Actor = Depends(get_current_actor),
) -> RedactionResult:
    """Preview deterministic PII and CI secret scrubbing prior to cloud inference."""
    _ = actor
    return redact_pii(payload.text)
