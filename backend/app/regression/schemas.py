from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RegressionBaselineCreateRequest(BaseModel):
    suite_name: str = Field(min_length=2, max_length=160)
    service_name: str = Field(min_length=2, max_length=160)
    gate_type: Literal["contract", "snapshot", "llm_eval", "combined"] = "combined"
    baseline_payload_json: dict[str, Any] = Field(default_factory=dict)


class RegressionBaselineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    suite_name: str
    service_name: str
    gate_type: str
    version: int
    baseline_payload_json: dict[str, Any]
    updated_by: str
    updated_at: datetime


class RegressionRunRequest(BaseModel):
    suite_name: str = Field(min_length=2, max_length=160)
    commit_sha: str = Field(min_length=4, max_length=64)
    branch: str = Field(default="main", min_length=1, max_length=120)
    latency_p95_ms: float = Field(default=0.0, ge=0.0)
    candidate_payload_json: dict[str, Any] = Field(default_factory=dict)


class RegressionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    baseline_id: str
    suite_name: str
    commit_sha: str
    branch: str
    gate_type: str
    status: str
    total_checks: int
    passed_checks: int
    failed_checks: int
    latency_p95_ms: float
    latency_drift_pct: float
    llm_eval_score: float | None = None
    candidate_payload_json: dict[str, Any]
    diff_report_json: dict[str, Any]
    ai_summary: str
    baseline_promoted: bool
    promotion_approval_id: str | None = None
    executed_by: str
    created_at: datetime
