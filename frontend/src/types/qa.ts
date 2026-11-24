export type ActorRole = 'viewer' | 'qa_engineer' | 'release_manager' | 'admin';

export interface ActorContext {
  email: string;
  role: ActorRole;
}

export interface HealthStatus {
  status: string;
  service: string;
  app_name: string;
  version: string;
  environment: string;
  llm_provider: string;
  database: string;
}

export interface OverviewSummary {
  test_suites_count: number;
  generated_cases_count: number;
  ci_runs_count: number;
  ci_failed_runs_count: number;
  flaky_tests_count: number;
  workflow_audits_count: number;
  regression_baselines_count: number;
  regression_runs_count: number;
  regression_failed_runs_count: number;
  release_candidates_count: number;
  go_releases_count: number;
  blocked_releases_count: number;
  pending_approvals_count: number;
  audit_events_count: number;
  audit_chain_valid: boolean;
  llm_provider: string;
  pii_redaction_enabled: boolean;
}

export interface SeedSummary {
  seeded: boolean;
  message: string;
  test_suites: number;
  ci_runs: number;
  regression_runs: number;
  release_candidates: number;
  pending_approvals: number;
}

export interface GeneratedTestCase {
  id: string;
  case_key: string;
  title: string;
  category: string;
  http_method: string;
  endpoint_or_route: string;
  assertions_json: string[];
  code_snippet: string;
  priority: string;
  created_at: string;
}

export interface TestSuiteItem {
  id: string;
  name: string;
  source_type: string;
  framework: string;
  target_base_url: string;
  spec_hash: string;
  case_count: number;
  status: string;
  generated_code: string;
  ai_summary: string;
  approval_id: string | null;
  created_by: string;
  created_at: string;
  cases: GeneratedTestCase[];
}

export interface FlowStepInput {
  action:
    | 'navigate'
    | 'fill'
    | 'click'
    | 'assert_visible'
    | 'assert_text'
    | 'assert_url'
    | 'api_check';
  target: string;
  value: string;
  expected: string;
}

export interface ExtractedCiError {
  test_name: string;
  signature: string;
  message: string;
}

export interface CiBuildRunItem {
  id: string;
  pipeline_name: string;
  branch: string;
  commit_sha: string;
  job_name: string;
  status: string;
  duration_seconds: number;
  root_cause_category: string;
  failure_signature: string;
  confidence: number;
  remediation_summary: string;
  ai_explanation: string;
  extracted_errors_json: ExtractedCiError[];
  created_at: string;
}

export interface FlakyClusterItem {
  test_name: string;
  suite_name: string;
  total_runs: number;
  pass_count: number;
  fail_count: number;
  pass_rate: number;
  transition_count: number;
  flakiness_score: number;
  is_flaky: boolean;
  dominant_error_signature: string;
  recommendation: string;
}

export interface WorkflowFinding {
  rule_id: string;
  severity: 'high' | 'medium' | 'low';
  title: string;
  detail: string;
  remediation: string;
}

export interface WorkflowAuditItem {
  id: string;
  workflow_name: string;
  filename: string;
  passed: boolean;
  score: number;
  findings_json: WorkflowFinding[];
  created_at: string;
}

export interface RegressionBaselineItem {
  id: string;
  suite_name: string;
  service_name: string;
  gate_type: string;
  version: number;
  baseline_payload_json: Record<string, unknown>;
  updated_by: string;
  updated_at: string;
}

export interface RegressionRunItem {
  id: string;
  baseline_id: string;
  suite_name: string;
  commit_sha: string;
  branch: string;
  gate_type: string;
  status: string;
  total_checks: number;
  passed_checks: number;
  failed_checks: number;
  latency_p95_ms: number;
  latency_drift_pct: number;
  llm_eval_score: number | null;
  candidate_payload_json: Record<string, unknown>;
  diff_report_json: {
    contract?: {
      breaking?: Record<string, unknown>[];
      additive?: Record<string, unknown>[];
    };
    snapshot?: Record<string, unknown>[];
    llm_eval?: Array<{
      id: string;
      score: number;
      baseline_score: number;
      passed: boolean;
      reason: string;
    }>;
    latency?: {
      baseline_p95_ms: number;
      candidate_p95_ms: number;
      drift_pct: number;
      warning: boolean;
      failed: boolean;
    };
  };
  ai_summary: string;
  baseline_promoted: boolean;
  promotion_approval_id: string | null;
  executed_by: string;
  created_at: string;
}

export interface SmokeProbeItem {
  id: string;
  probe_name: string;
  target_url: string;
  http_method: string;
  expected_status: number;
  actual_status: number | null;
  latency_ms: number;
  max_latency_ms: number;
  expected_body_contains: string;
  passed: boolean;
  mode: string;
  error_detail: string;
  executed_at: string;
}

export interface ChecklistGateItem {
  gate: string;
  label: string;
  passed: boolean;
  detail: string;
}

export interface ReleaseCandidateItem {
  id: string;
  version_tag: string;
  service_name: string;
  environment: string;
  commit_sha: string;
  previous_version_tag: string;
  rollback_runbook_url: string;
  rollback_verified: boolean;
  canary_error_rate_pct: number;
  canary_p95_latency_ms: number;
  canary_traffic_pct: number;
  regression_run_id: string | null;
  readiness_score: number;
  decision: string;
  status: string;
  checklist_json: ChecklistGateItem[];
  ai_readiness_brief: string;
  approval_id: string | null;
  rollback_approval_id: string | null;
  rollback_executed_at: string | null;
  created_by: string;
  created_at: string;
  smoke_probes: SmokeProbeItem[];
}

export interface ApprovalRequestItem {
  id: string;
  entity_type: string;
  entity_id: string;
  action_requested: string;
  summary: string;
  risk_level: string;
  status: string;
  requested_by: string;
  decided_by: string | null;
  decision_notes: string | null;
  created_at: string;
  decided_at: string | null;
}

export interface AuditEventItem {
  id: string;
  sequence_no: number;
  event_type: string;
  actor_email: string;
  actor_role: string;
  entity_type: string;
  entity_id: string;
  action: string;
  details_json: Record<string, unknown>;
  prev_hash: string;
  event_hash: string;
  created_at: string;
}

export interface AuditChainVerify {
  valid: boolean;
  total_events: number;
  head_hash: string;
  broken_sequence_no: number | null;
  message: string;
}

export interface RedactionFinding {
  category: string;
  count: number;
  placeholder: string;
}

export interface PiiRedactResult {
  redacted_text: string;
  findings: RedactionFinding[];
  total_redactions: number;
}
