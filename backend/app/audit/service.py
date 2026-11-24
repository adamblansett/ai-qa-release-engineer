import hashlib
import json
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.schemas import AuditChainVerifyOut
from app.core.auth import Actor
from app.db.base import utcnow
from app.db.models import (
    ApprovalRequest,
    AuditEvent,
    RegressionBaseline,
    RegressionRun,
    ReleaseCandidate,
    TestSuite,
)


def compute_event_hash(
    *,
    sequence_no: int,
    event_type: str,
    actor_email: str,
    actor_role: str,
    entity_type: str,
    entity_id: str,
    action: str,
    details: dict[str, Any],
    prev_hash: str,
) -> str:
    """Compute a deterministic SHA-256 hash chaining an audit event to prev_hash."""
    canonical = json.dumps(
        {
            "sequence_no": sequence_no,
            "event_type": event_type,
            "actor_email": actor_email,
            "actor_role": actor_role,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "details": details,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def record_audit_event(
    db: AsyncSession,
    *,
    event_type: str,
    actor: Actor,
    entity_type: str,
    entity_id: str,
    action: str,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append an immutable hash-chained event to the release governance audit log."""
    stmt = select(AuditEvent).order_by(AuditEvent.sequence_no.desc()).limit(1)
    latest = (await db.execute(stmt)).scalar_one_or_none()

    next_seq = (latest.sequence_no + 1) if latest is not None else 1
    prev_hash = latest.event_hash if latest is not None else "GENESIS"
    clean_details = details or {}

    event_hash = compute_event_hash(
        sequence_no=next_seq,
        event_type=event_type,
        actor_email=actor.email,
        actor_role=actor.role,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        details=clean_details,
        prev_hash=prev_hash,
    )
    event = AuditEvent(
        sequence_no=next_seq,
        event_type=event_type,
        actor_email=actor.email,
        actor_role=actor.role,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        details_json=clean_details,
        prev_hash=prev_hash,
        event_hash=event_hash,
    )
    db.add(event)
    await db.flush()
    return event


async def verify_audit_chain(db: AsyncSession) -> AuditChainVerifyOut:
    """Recompute every SHA-256 link in audit_events and report integrity status."""
    stmt = select(AuditEvent).order_by(AuditEvent.sequence_no.asc())
    events = list((await db.execute(stmt)).scalars().all())
    if not events:
        return AuditChainVerifyOut(
            valid=True,
            total_events=0,
            head_hash="GENESIS",
            broken_sequence_no=None,
            message="Audit trail is empty (GENESIS state verified).",
        )

    expected_prev = "GENESIS"
    expected_seq = 1
    for ev in events:
        if ev.sequence_no != expected_seq or ev.prev_hash != expected_prev:
            return AuditChainVerifyOut(
                valid=False,
                total_events=len(events),
                head_hash=events[-1].event_hash,
                broken_sequence_no=ev.sequence_no,
                message=(
                    f"Chain linkage mismatch at sequence #{ev.sequence_no}: "
                    f"expected prev_hash={expected_prev[:12]}..."
                ),
            )
        recomputed = compute_event_hash(
            sequence_no=ev.sequence_no,
            event_type=ev.event_type,
            actor_email=ev.actor_email,
            actor_role=ev.actor_role,
            entity_type=ev.entity_type,
            entity_id=ev.entity_id,
            action=ev.action,
            details=ev.details_json,
            prev_hash=ev.prev_hash,
        )
        if ev.event_hash != recomputed:
            return AuditChainVerifyOut(
                valid=False,
                total_events=len(events),
                head_hash=events[-1].event_hash,
                broken_sequence_no=ev.sequence_no,
                message=f"Hash tamper detected at sequence #{ev.sequence_no}.",
            )
        expected_prev = ev.event_hash
        expected_seq += 1

    return AuditChainVerifyOut(
        valid=True,
        total_events=len(events),
        head_hash=events[-1].event_hash,
        broken_sequence_no=None,
        message=f"All {len(events)} audit events verified intact.",
    )


async def create_approval_request(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    action_requested: str,
    summary: str,
    risk_level: str,
    requested_by: str,
) -> ApprovalRequest:
    """Create a pending human-in-the-loop approval request."""
    approval = ApprovalRequest(
        entity_type=entity_type,
        entity_id=entity_id,
        action_requested=action_requested,
        summary=summary,
        risk_level=risk_level,
        status="pending",
        requested_by=requested_by,
    )
    db.add(approval)
    await db.flush()
    return approval


async def decide_approval(
    db: AsyncSession,
    *,
    approval_id: str,
    decision: Literal["approved", "rejected"],
    notes: str,
    actor: Actor,
) -> ApprovalRequest:
    """Approve or reject a pending HITL gate and apply domain side effects atomically."""
    approval = await db.get(ApprovalRequest, approval_id)
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request '{approval_id}' not found.",
        )
    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval request '{approval_id}' is already '{approval.status}'.",
        )

    approval.status = decision
    approval.decided_by = actor.email
    approval.decision_notes = notes.strip() or f"{decision} by {actor.email}"
    approval.decided_at = utcnow()

    if approval.entity_type == "release_promotion":
        release = await db.get(ReleaseCandidate, approval.entity_id)
        if release is None:
            release = (
                await db.execute(
                    select(ReleaseCandidate).where(ReleaseCandidate.approval_id == approval.id)
                )
            ).scalar_one_or_none()
        if release is not None:
            if decision == "approved":
                release.status = "approved"
                release.decision = "go"
            else:
                release.status = "blocked"
                release.decision = "no_go"

    elif approval.entity_type == "rollback_execution":
        release = await db.get(ReleaseCandidate, approval.entity_id)
        if release is None:
            release = (
                await db.execute(
                    select(ReleaseCandidate).where(
                        ReleaseCandidate.rollback_approval_id == approval.id
                    )
                )
            ).scalar_one_or_none()
        if release is not None and decision == "approved":
            release.status = "rolled_back"
            release.decision = "no_go"
            release.rollback_executed_at = utcnow()

    elif approval.entity_type == "baseline_promotion":
        run = await db.get(RegressionRun, approval.entity_id)
        if run is None:
            run = (
                await db.execute(
                    select(RegressionRun).where(
                        RegressionRun.promotion_approval_id == approval.id
                    )
                )
            ).scalar_one_or_none()
        if run is not None and decision == "approved":
            run.baseline_promoted = True
            baseline = await db.get(RegressionBaseline, run.baseline_id)
            if baseline is not None:
                baseline.version += 1
                baseline.baseline_payload_json = run.candidate_payload_json
                baseline.updated_by = actor.email
                baseline.updated_at = utcnow()

    elif approval.entity_type == "test_suite_publish":
        suite = await db.get(TestSuite, approval.entity_id)
        if suite is None:
            suite = (
                await db.execute(select(TestSuite).where(TestSuite.approval_id == approval.id))
            ).scalar_one_or_none()
        if suite is not None:
            suite.status = "approved" if decision == "approved" else "rejected"

    await record_audit_event(
        db,
        event_type="approval.decided",
        actor=actor,
        entity_type=approval.entity_type,
        entity_id=approval.entity_id,
        action=decision,
        details={
            "approval_id": approval.id,
            "decision": decision,
            "notes": approval.decision_notes,
            "action_requested": approval.action_requested,
        },
    )
    await db.commit()
    await db.refresh(approval)
    return approval
