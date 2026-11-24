from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ReleaseCandidateCreateRequest(BaseModel):
    version_tag: str = Field(min_length=1, max_length=64)
    service_name: str = Field(min_length=2, max_length=160)
    environment: str = Field(default="production", min_length=2, max_length=40)
    commit_sha: str = Field(min_length=4, max_length=64)
    previous_version_tag: str = Field(default="", max_length=64)
    rollback_runbook_url: str = Field(default="", max_length=500)
    rollback_verified: bool = False
    canary_error_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    canary_p95_latency_ms: float = Field(default=0.0, ge=0.0)
    canary_traffic_pct: int = Field(default=10, ge=0, le=100)
    regression_run_id: str | None = None


class SmokeProbeInput(BaseModel):
    probe_name: str = Field(min_length=1, max_length=160)
    target_url: str = Field(min_length=4, max_length=500)
    http_method: Literal["GET", "POST", "HEAD"] = "GET"
    expected_status: int = Field(default=200, ge=100, le=599)
    max_latency_ms: float = Field(default=500.0, gt=0.0)
    expected_body_contains: str = Field(default="", max_length=255)
    mode: Literal["simulated", "live_http"] = "simulated"
    simulated_status: int | None = Field(default=None, ge=100, le=599)
    simulated_latency_ms: float = Field(default=45.0, ge=0.0)
    simulated_body: str = Field(default='{"status":"ok"}', max_length=4000)


class SmokeProbeBatchRequest(BaseModel):
    probes: list[SmokeProbeInput] = Field(min_length=1, max_length=25)


class ReleaseEvaluateRequest(BaseModel):
    canary_error_rate_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    canary_p95_latency_ms: float | None = Field(default=None, ge=0.0)
    canary_traffic_pct: int | None = Field(default=None, ge=0, le=100)
    rollback_verified: bool | None = None
    rollback_runbook_url: str | None = Field(default=None, max_length=500)
    regression_run_id: str | None = None


class SmokeProbeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    probe_name: str
    target_url: str
    http_method: str
    expected_status: int
    actual_status: int | None = None
    latency_ms: float
    max_latency_ms: float
    expected_body_contains: str
    passed: bool
    mode: str
    error_detail: str
    executed_at: datetime


class ChecklistGateOut(BaseModel):
    gate: str
    label: str
    passed: bool
    detail: str


class ReleaseCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version_tag: str
    service_name: str
    environment: str
    commit_sha: str
    previous_version_tag: str
    rollback_runbook_url: str
    rollback_verified: bool
    canary_error_rate_pct: float
    canary_p95_latency_ms: float
    canary_traffic_pct: int
    regression_run_id: str | None = None
    readiness_score: int
    decision: str
    status: str
    checklist_json: list[dict[str, Any]]
    ai_readiness_brief: str
    approval_id: str | None = None
    rollback_approval_id: str | None = None
    rollback_executed_at: datetime | None = None
    created_by: str
    created_at: datetime
    smoke_probes: list[SmokeProbeOut] = Field(default_factory=list)
