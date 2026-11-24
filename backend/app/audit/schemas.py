from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    notes: str = Field(default="", max_length=1000)


class ApprovalRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    entity_type: str
    entity_id: str
    action_requested: str
    summary: str
    risk_level: str
    status: str
    requested_by: str
    decided_by: str | None = None
    decision_notes: str | None = None
    created_at: datetime
    decided_at: datetime | None = None


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sequence_no: int
    event_type: str
    actor_email: str
    actor_role: str
    entity_type: str
    entity_id: str
    action: str
    details_json: dict[str, Any]
    prev_hash: str
    event_hash: str
    created_at: datetime


class AuditChainVerifyOut(BaseModel):
    valid: bool
    total_events: int
    head_hash: str
    broken_sequence_no: int | None = None
    message: str


class PiiRedactRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
