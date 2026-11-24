"""Initial AI QA & Release Engineer schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_email", sa.String(length=255), nullable=False),
        sa.Column("actor_role", sa.String(length=40), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_sequence_no", "audit_events", ["sequence_no"], unique=True)
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_entity_type", "audit_events", ["entity_type"])
    op.create_index("ix_audit_events_entity_id", "audit_events", ["entity_id"])

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("action_requested", sa.String(length=120), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approval_requests_entity_type", "approval_requests", ["entity_type"])
    op.create_index("ix_approval_requests_entity_id", "approval_requests", ["entity_id"])
    op.create_index("ix_approval_requests_status", "approval_requests", ["status"])

    op.create_table(
        "test_suites",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("framework", sa.String(length=32), nullable=False),
        sa.Column("target_base_url", sa.String(length=500), nullable=False),
        sa.Column("source_spec_raw", sa.Text(), nullable=False),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("generated_code", sa.Text(), nullable=False),
        sa.Column("ai_summary", sa.Text(), nullable=False),
        sa.Column(
            "approval_id",
            sa.String(length=36),
            sa.ForeignKey("approval_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_test_suites_name", "test_suites", ["name"])
    op.create_index("ix_test_suites_spec_hash", "test_suites", ["spec_hash"])
    op.create_index("ix_test_suites_status", "test_suites", ["status"])

    op.create_table(
        "generated_test_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "suite_id",
            sa.String(length=36),
            sa.ForeignKey("test_suites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_key", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("http_method", sa.String(length=16), nullable=False),
        sa.Column("endpoint_or_route", sa.String(length=300), nullable=False),
        sa.Column("assertions_json", sa.JSON(), nullable=False),
        sa.Column("code_snippet", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generated_test_cases_suite_id", "generated_test_cases", ["suite_id"])

    op.create_table(
        "ci_build_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("pipeline_name", sa.String(length=160), nullable=False),
        sa.Column("branch", sa.String(length=120), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("job_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("raw_log", sa.Text(), nullable=False),
        sa.Column("root_cause_category", sa.String(length=64), nullable=False),
        sa.Column("failure_signature", sa.String(length=300), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("remediation_summary", sa.Text(), nullable=False),
        sa.Column("ai_explanation", sa.Text(), nullable=False),
        sa.Column("extracted_errors_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ci_build_runs_pipeline_name", "ci_build_runs", ["pipeline_name"])
    op.create_index("ix_ci_build_runs_branch", "ci_build_runs", ["branch"])
    op.create_index("ix_ci_build_runs_commit_sha", "ci_build_runs", ["commit_sha"])
    op.create_index("ix_ci_build_runs_status", "ci_build_runs", ["status"])
    op.create_index(
        "ix_ci_build_runs_root_cause_category", "ci_build_runs", ["root_cause_category"]
    )

    op.create_table(
        "test_execution_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "build_run_id",
            sa.String(length=36),
            sa.ForeignKey("ci_build_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("test_name", sa.String(length=300), nullable=False),
        sa.Column("suite_name", sa.String(length=160), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("error_signature", sa.String(length=300), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_test_execution_records_build_run_id", "test_execution_records", ["build_run_id"]
    )
    op.create_index("ix_test_execution_records_test_name", "test_execution_records", ["test_name"])
    op.create_index("ix_test_execution_records_outcome", "test_execution_records", ["outcome"])

    op.create_table(
        "workflow_audits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_name", sa.String(length=160), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("workflow_yaml", sa.Text(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("findings_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "regression_baselines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("suite_name", sa.String(length=160), nullable=False),
        sa.Column("service_name", sa.String(length=160), nullable=False),
        sa.Column("gate_type", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("baseline_payload_json", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_regression_baselines_suite_name", "regression_baselines", ["suite_name"], unique=True
    )

    op.create_table(
        "regression_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "baseline_id",
            sa.String(length=36),
            sa.ForeignKey("regression_baselines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("suite_name", sa.String(length=160), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("branch", sa.String(length=120), nullable=False),
        sa.Column("gate_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_checks", sa.Integer(), nullable=False),
        sa.Column("passed_checks", sa.Integer(), nullable=False),
        sa.Column("failed_checks", sa.Integer(), nullable=False),
        sa.Column("latency_p95_ms", sa.Float(), nullable=False),
        sa.Column("latency_drift_pct", sa.Float(), nullable=False),
        sa.Column("llm_eval_score", sa.Float(), nullable=True),
        sa.Column("candidate_payload_json", sa.JSON(), nullable=False),
        sa.Column("diff_report_json", sa.JSON(), nullable=False),
        sa.Column("ai_summary", sa.Text(), nullable=False),
        sa.Column("baseline_promoted", sa.Boolean(), nullable=False),
        sa.Column(
            "promotion_approval_id",
            sa.String(length=36),
            sa.ForeignKey("approval_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("executed_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_regression_runs_baseline_id", "regression_runs", ["baseline_id"])
    op.create_index("ix_regression_runs_suite_name", "regression_runs", ["suite_name"])
    op.create_index("ix_regression_runs_commit_sha", "regression_runs", ["commit_sha"])
    op.create_index("ix_regression_runs_status", "regression_runs", ["status"])

    op.create_table(
        "release_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("version_tag", sa.String(length=64), nullable=False),
        sa.Column("service_name", sa.String(length=160), nullable=False),
        sa.Column("environment", sa.String(length=40), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("previous_version_tag", sa.String(length=64), nullable=False),
        sa.Column("rollback_runbook_url", sa.String(length=500), nullable=False),
        sa.Column("rollback_verified", sa.Boolean(), nullable=False),
        sa.Column("canary_error_rate_pct", sa.Float(), nullable=False),
        sa.Column("canary_p95_latency_ms", sa.Float(), nullable=False),
        sa.Column("canary_traffic_pct", sa.Integer(), nullable=False),
        sa.Column(
            "regression_run_id",
            sa.String(length=36),
            sa.ForeignKey("regression_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("readiness_score", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("checklist_json", sa.JSON(), nullable=False),
        sa.Column("ai_readiness_brief", sa.Text(), nullable=False),
        sa.Column(
            "approval_id",
            sa.String(length=36),
            sa.ForeignKey("approval_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "rollback_approval_id",
            sa.String(length=36),
            sa.ForeignKey("approval_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rollback_executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_release_candidates_version_tag", "release_candidates", ["version_tag"], unique=True
    )
    op.create_index("ix_release_candidates_commit_sha", "release_candidates", ["commit_sha"])
    op.create_index("ix_release_candidates_decision", "release_candidates", ["decision"])
    op.create_index("ix_release_candidates_status", "release_candidates", ["status"])

    op.create_table(
        "smoke_probe_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "release_id",
            sa.String(length=36),
            sa.ForeignKey("release_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("probe_name", sa.String(length=160), nullable=False),
        sa.Column("target_url", sa.String(length=500), nullable=False),
        sa.Column("http_method", sa.String(length=16), nullable=False),
        sa.Column("expected_status", sa.Integer(), nullable=False),
        sa.Column("actual_status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("max_latency_ms", sa.Float(), nullable=False),
        sa.Column("expected_body_contains", sa.String(length=255), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_smoke_probe_results_release_id", "smoke_probe_results", ["release_id"])


def downgrade() -> None:
    op.drop_table("smoke_probe_results")
    op.drop_table("release_candidates")
    op.drop_table("regression_runs")
    op.drop_table("regression_baselines")
    op.drop_table("workflow_audits")
    op.drop_table("test_execution_records")
    op.drop_table("ci_build_runs")
    op.drop_table("generated_test_cases")
    op.drop_table("test_suites")
    op.drop_table("approval_requests")
    op.drop_table("audit_events")
