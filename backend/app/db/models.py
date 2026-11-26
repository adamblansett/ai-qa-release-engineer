from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, new_id, utcnow


class AuditEvent(Base):
    """Immutable hash-chained QA & release governance audit log entry."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sequence_no: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    actor_email: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ApprovalRequest(Base):
    """Human-in-the-loop approval gate for promotions, rollbacks, baselines, and suites."""

    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    action_requested: Mapped[str] = mapped_column(String(120), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(24), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(24), index=True, nullable=False, default="pending")
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TestSuite(Base):
    """Synthesized Playwright or pytest test suite generated from OpenAPI or user flows."""

    __tablename__ = "test_suites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    framework: Mapped[str] = mapped_column(String(32), nullable=False)
    target_base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    source_spec_raw: Mapped[str] = mapped_column(Text, nullable=False)
    spec_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="draft")
    generated_code: Mapped[str] = mapped_column(Text, nullable=False)
    ai_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approval_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("approval_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    cases: Mapped[list["GeneratedTestCase"]] = relationship(
        back_populates="suite",
        cascade="all, delete-orphan",
        order_by="GeneratedTestCase.created_at",
    )


class GeneratedTestCase(Base):
    """Individual synthesized test case with schema/UI assertions."""

    __tablename__ = "generated_test_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    suite_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_suites.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    case_key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    http_method: Mapped[str] = mapped_column(String(16), nullable=False, default="FLOW")
    endpoint_or_route: Mapped[str] = mapped_column(String(300), nullable=False)
    assertions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    code_snippet: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="P1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    suite: Mapped[TestSuite] = relationship(back_populates="cases")


class CiBuildRun(Base):
    """Analyzed CI/CD build run with root-cause classification and extracted errors."""

    __tablename__ = "ci_build_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    pipeline_name: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    branch: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    job_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    raw_log: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause_category: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False, default="none"
    )
    failure_signature: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    remediation_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ai_explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extracted_errors_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    embedding_json: Mapped[list[float]] = mapped_column(
        JSON, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    test_records: Mapped[list["TestExecutionRecord"]] = relationship(
        back_populates="build_run",
        cascade="all, delete-orphan",
    )


class TestExecutionRecord(Base):
    """Per-test execution outcome used for flaky-test clustering."""

    __tablename__ = "test_execution_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    build_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ci_build_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    test_name: Mapped[str] = mapped_column(String(300), index=True, nullable=False)
    suite_name: Mapped[str] = mapped_column(String(160), nullable=False, default="default")
    outcome: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_signature: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    build_run: Mapped[CiBuildRun] = relationship(back_populates="test_records")


class WorkflowAudit(Base):
    """GitHub Actions workflow security & reliability validation audit."""

    __tablename__ = "workflow_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_name: Mapped[str] = mapped_column(String(160), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    workflow_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    findings_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class RegressionBaseline(Base):
    """Deterministic contract, snapshot, and LLM-eval baseline definition."""

    __tablename__ = "regression_baselines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    suite_name: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    service_name: Mapped[str] = mapped_column(String(160), nullable=False)
    gate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    baseline_payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    runs: Mapped[list["RegressionRun"]] = relationship(
        back_populates="baseline",
        cascade="all, delete-orphan",
    )


class RegressionRun(Base):
    """Execution result comparing candidate contract/snapshot/LLM outputs against baseline."""

    __tablename__ = "regression_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    baseline_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("regression_baselines.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    suite_name: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    branch: Mapped[str] = mapped_column(String(120), nullable=False)
    gate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    total_checks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_checks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_checks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_p95_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_drift_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    llm_eval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    candidate_payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    diff_report_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    ai_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    baseline_promoted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    promotion_approval_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("approval_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    executed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    baseline: Mapped[RegressionBaseline] = relationship(back_populates="runs")


class ReleaseCandidate(Base):
    """Release candidate with canary metrics, 6-gate Go/No-Go checklist, and HITL gates."""

    __tablename__ = "release_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    version_tag: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    service_name: Mapped[str] = mapped_column(String(160), nullable=False)
    environment: Mapped[str] = mapped_column(String(40), nullable=False, default="production")
    commit_sha: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    previous_version_tag: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    rollback_runbook_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    rollback_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    canary_error_rate_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    canary_p95_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    canary_traffic_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    regression_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("regression_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    readiness_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decision: Mapped[str] = mapped_column(String(24), index=True, nullable=False, default="pending")
    status: Mapped[str] = mapped_column(
        String(32), index=True, nullable=False, default="evaluating"
    )
    checklist_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    ai_readiness_brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approval_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("approval_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    rollback_approval_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("approval_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    rollback_executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    smoke_probes: Mapped[list["SmokeProbeResult"]] = relationship(
        back_populates="release",
        cascade="all, delete-orphan",
        order_by="SmokeProbeResult.executed_at.desc()",
    )


class SmokeProbeResult(Base):
    """Post-deploy HTTP smoke probe assertion tied to a release candidate."""

    __tablename__ = "smoke_probe_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    release_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("release_candidates.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    probe_name: Mapped[str] = mapped_column(String(160), nullable=False)
    target_url: Mapped[str] = mapped_column(String(500), nullable=False)
    http_method: Mapped[str] = mapped_column(String(16), nullable=False, default="GET")
    expected_status: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    actual_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=500.0)
    expected_body_contains: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False, default="simulated")
    error_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    release: Mapped[ReleaseCandidate] = relationship(back_populates="smoke_probes")


class ApiKey(Base):
    """Hashed API key for headless CI/CD pipelines and production automation."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    owner_email: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BackgroundJob(Base):
    """Asynchronous or inline QA & release verification background job."""

    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="inline")
    status: Mapped[str] = mapped_column(String(24), index=True, nullable=False, default="queued")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

