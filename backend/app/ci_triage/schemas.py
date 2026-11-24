from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TestExecutionInput(BaseModel):
    test_name: str = Field(min_length=1, max_length=300)
    suite_name: str = Field(default="default", max_length=160)
    outcome: Literal["passed", "failed", "skipped"]
    duration_ms: float = Field(default=0.0, ge=0.0)
    error_message: str = Field(default="", max_length=4000)


class CiLogAnalyzeRequest(BaseModel):
    pipeline_name: str = Field(min_length=1, max_length=160)
    branch: str = Field(default="main", min_length=1, max_length=120)
    commit_sha: str = Field(min_length=4, max_length=64)
    job_name: str = Field(min_length=1, max_length=160)
    status: Literal["passed", "failed"] | None = None
    duration_seconds: float = Field(default=0.0, ge=0.0)
    raw_log: str = Field(min_length=1, max_length=250000)
    test_records: list[TestExecutionInput] = Field(default_factory=list)


class CiBuildRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_name: str
    branch: str
    commit_sha: str
    job_name: str
    status: str
    duration_seconds: float
    root_cause_category: str
    failure_signature: str
    confidence: float
    remediation_summary: str
    ai_explanation: str
    extracted_errors_json: list[dict[str, Any]]
    created_at: datetime


class FlakyClusterOut(BaseModel):
    test_name: str
    suite_name: str
    total_runs: int
    pass_count: int
    fail_count: int
    pass_rate: float
    transition_count: int
    flakiness_score: float
    is_flaky: bool
    dominant_error_signature: str
    recommendation: str


class WorkflowAuditRequest(BaseModel):
    workflow_name: str = Field(min_length=1, max_length=160)
    filename: str = Field(default=".github/workflows/ci.yml", max_length=255)
    workflow_yaml: str = Field(min_length=5, max_length=200000)


class WorkflowFindingOut(BaseModel):
    rule_id: str
    severity: Literal["high", "medium", "low"]
    title: str
    detail: str
    remediation: str


class WorkflowAuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_name: str
    filename: str
    passed: bool
    score: int
    findings_json: list[dict[str, Any]]
    created_at: datetime
