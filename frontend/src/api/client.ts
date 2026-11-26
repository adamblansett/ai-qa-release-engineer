import type {
  ActorContext,
  ActorRole,
  ApiKeyCreateResponse,
  ApiKeyItem,
  ApprovalRequestItem,
  AuditChainVerify,
  AuditEventItem,
  BackgroundJobItem,
  CiBuildRunItem,
  FlakyClusterItem,
  FlowStepInput,
  GitHubCheckPublishResponse,
  GitHubWebhookResponse,
  HealthStatus,
  OverviewSummary,
  PiiRedactResult,
  RegressionBaselineItem,
  RegressionRunItem,
  ReleaseCandidateItem,
  SeedSummary,
  SemanticClusterItem,
  TestSuiteItem,
  TokenIssueResponse,
  WorkflowAuditItem,
} from '../types/qa';

export class ApiClientError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiClientError';
    this.status = status;
  }
}

async function requestJson<T>(
  path: string,
  actor: ActorContext,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (actor.authMode === 'bearer_token' && actor.token) {
    headers.set('Authorization', `Bearer ${actor.token}`);
  } else if (actor.authMode === 'api_key' && actor.apiKey) {
    headers.set('X-API-Key', actor.apiKey);
  } else {
    headers.set('X-Actor-Email', actor.email);
    headers.set('X-Actor-Role', actor.role);
  }
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as {
        detail?: string | { message?: string };
      };
      if (typeof payload.detail === 'string') {
        message = payload.detail;
      } else if (payload.detail && typeof payload.detail.message === 'string') {
        message = payload.detail.message;
      }
    } catch {
      // ignore non-JSON error body
    }
    throw new ApiClientError(message, response.status);
  }
  return (await response.json()) as T;
}

export async function fetchHealth(): Promise<HealthStatus> {
  const response = await fetch('/api/v1/health');
  if (!response.ok) {
    throw new ApiClientError('API health check failed', response.status);
  }
  return (await response.json()) as HealthStatus;
}

export function fetchOverview(actor: ActorContext): Promise<OverviewSummary> {
  return requestJson<OverviewSummary>('/api/v1/overview', actor);
}

export function seedDemoData(actor: ActorContext, reset = false): Promise<SeedSummary> {
  return requestJson<SeedSummary>(`/api/v1/seed/demo?reset=${reset}`, actor, {
    method: 'POST',
  });
}

// --- TestGen ---

export function fetchTestSuites(actor: ActorContext): Promise<TestSuiteItem[]> {
  return requestJson<TestSuiteItem[]>('/api/v1/testgen/suites', actor);
}

export function synthesizeOpenApiSuite(
  actor: ActorContext,
  payload: {
    suite_name: string;
    spec_text: string;
    framework: 'playwright' | 'pytest';
    target_base_url: string;
    include_negative_cases: boolean;
    include_auth_cases: boolean;
  },
): Promise<TestSuiteItem> {
  return requestJson<TestSuiteItem>('/api/v1/testgen/synthesize/openapi', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function synthesizeFlowSuite(
  actor: ActorContext,
  payload: {
    suite_name: string;
    flow_name: string;
    target_base_url: string;
    steps: FlowStepInput[];
  },
): Promise<TestSuiteItem> {
  return requestJson<TestSuiteItem>('/api/v1/testgen/synthesize/flow', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function requestSuiteApproval(
  actor: ActorContext,
  suiteId: string,
): Promise<ApprovalRequestItem> {
  return requestJson<ApprovalRequestItem>(
    `/api/v1/testgen/suites/${suiteId}/request-approval`,
    actor,
    { method: 'POST' },
  );
}

// --- CI Triage ---

export function fetchCiRuns(actor: ActorContext): Promise<CiBuildRunItem[]> {
  return requestJson<CiBuildRunItem[]>('/api/v1/ci-triage/runs', actor);
}

export function analyzeCiLog(
  actor: ActorContext,
  payload: {
    pipeline_name: string;
    branch: string;
    commit_sha: string;
    job_name: string;
    raw_log: string;
  },
): Promise<CiBuildRunItem> {
  return requestJson<CiBuildRunItem>('/api/v1/ci-triage/analyze', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function fetchFlakyClusters(actor: ActorContext): Promise<FlakyClusterItem[]> {
  return requestJson<FlakyClusterItem[]>('/api/v1/ci-triage/flaky-clusters', actor);
}

export function fetchWorkflowAudits(actor: ActorContext): Promise<WorkflowAuditItem[]> {
  return requestJson<WorkflowAuditItem[]>('/api/v1/ci-triage/workflow-audits', actor);
}

export function auditWorkflowYaml(
  actor: ActorContext,
  payload: {
    workflow_name: string;
    filename: string;
    workflow_yaml: string;
  },
): Promise<WorkflowAuditItem> {
  return requestJson<WorkflowAuditItem>('/api/v1/ci-triage/workflow-audits', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// --- Regression ---

export function fetchRegressionBaselines(
  actor: ActorContext,
): Promise<RegressionBaselineItem[]> {
  return requestJson<RegressionBaselineItem[]>('/api/v1/regression/baselines', actor);
}

export function fetchRegressionRuns(actor: ActorContext): Promise<RegressionRunItem[]> {
  return requestJson<RegressionRunItem[]>('/api/v1/regression/runs', actor);
}

export function executeRegressionRun(
  actor: ActorContext,
  payload: {
    suite_name: string;
    commit_sha: string;
    branch: string;
    latency_p95_ms: number;
    candidate_payload_json: Record<string, unknown>;
  },
): Promise<RegressionRunItem> {
  return requestJson<RegressionRunItem>('/api/v1/regression/runs', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function proposeBaselinePromotion(
  actor: ActorContext,
  runId: string,
): Promise<ApprovalRequestItem> {
  return requestJson<ApprovalRequestItem>(
    `/api/v1/regression/runs/${runId}/propose-baseline`,
    actor,
    { method: 'POST' },
  );
}

// --- Release Gate ---

export function fetchReleases(actor: ActorContext): Promise<ReleaseCandidateItem[]> {
  return requestJson<ReleaseCandidateItem[]>('/api/v1/release-gate/releases', actor);
}

export function createReleaseCandidate(
  actor: ActorContext,
  payload: {
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
  },
): Promise<ReleaseCandidateItem> {
  return requestJson<ReleaseCandidateItem>('/api/v1/release-gate/releases', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function runSmokeProbes(
  actor: ActorContext,
  releaseId: string,
  probes: Array<{
    probe_name: string;
    target_url: string;
    http_method: 'GET' | 'POST' | 'HEAD';
    expected_status: number;
    max_latency_ms: number;
    expected_body_contains: string;
    mode: 'simulated' | 'live_http';
    simulated_status?: number;
    simulated_latency_ms?: number;
    simulated_body?: string;
  }>,
): Promise<ReleaseCandidateItem> {
  return requestJson<ReleaseCandidateItem>(
    `/api/v1/release-gate/releases/${releaseId}/probes`,
    actor,
    {
      method: 'POST',
      body: JSON.stringify({ probes }),
    },
  );
}

export function evaluateRelease(
  actor: ActorContext,
  releaseId: string,
  payload: {
    canary_error_rate_pct?: number;
    canary_p95_latency_ms?: number;
    rollback_verified?: boolean;
  },
): Promise<ReleaseCandidateItem> {
  return requestJson<ReleaseCandidateItem>(
    `/api/v1/release-gate/releases/${releaseId}/evaluate`,
    actor,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  );
}

export function requestReleasePromotion(
  actor: ActorContext,
  releaseId: string,
): Promise<ApprovalRequestItem> {
  return requestJson<ApprovalRequestItem>(
    `/api/v1/release-gate/releases/${releaseId}/request-promotion`,
    actor,
    { method: 'POST' },
  );
}

export function requestReleaseRollback(
  actor: ActorContext,
  releaseId: string,
): Promise<ApprovalRequestItem> {
  return requestJson<ApprovalRequestItem>(
    `/api/v1/release-gate/releases/${releaseId}/request-rollback`,
    actor,
    { method: 'POST' },
  );
}

// --- Audit & HITL ---

export function fetchApprovals(actor: ActorContext): Promise<ApprovalRequestItem[]> {
  return requestJson<ApprovalRequestItem[]>('/api/v1/audit/approvals', actor);
}

export function decideApproval(
  actor: ActorContext,
  approvalId: string,
  decision: 'approved' | 'rejected',
  notes: string,
): Promise<ApprovalRequestItem> {
  return requestJson<ApprovalRequestItem>(`/api/v1/audit/approvals/${approvalId}/decide`, actor, {
    method: 'POST',
    body: JSON.stringify({ decision, notes }),
  });
}

export function fetchAuditEvents(actor: ActorContext): Promise<AuditEventItem[]> {
  return requestJson<AuditEventItem[]>('/api/v1/audit/events', actor);
}

export function verifyAuditChain(actor: ActorContext): Promise<AuditChainVerify> {
  return requestJson<AuditChainVerify>('/api/v1/audit/events/verify', actor);
}

export function redactPiiText(actor: ActorContext, text: string): Promise<PiiRedactResult> {
  return requestJson<PiiRedactResult>('/api/v1/audit/pii/redact', actor, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

// --- Phase 2: Auth Tokens, API Keys, Reports, Semantic Clusters, Integrations, Jobs ---

export async function issueDevToken(
  email: string,
  role: ActorRole,
): Promise<TokenIssueResponse> {
  const response = await fetch('/api/v1/auth/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, role }),
  });
  if (!response.ok) {
    throw new ApiClientError('Token issuance failed', response.status);
  }
  return (await response.json()) as TokenIssueResponse;
}

export function fetchApiKeys(actor: ActorContext): Promise<ApiKeyItem[]> {
  return requestJson<ApiKeyItem[]>('/api/v1/auth/api-keys', actor);
}

export function createApiKey(
  actor: ActorContext,
  payload: { name: string; role: ActorRole; owner_email: string },
): Promise<ApiKeyCreateResponse> {
  return requestJson<ApiKeyCreateResponse>('/api/v1/auth/api-keys', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function revokeApiKey(actor: ActorContext, keyId: string): Promise<ApiKeyItem> {
  return requestJson<ApiKeyItem>(`/api/v1/auth/api-keys/${keyId}`, actor, {
    method: 'DELETE',
  });
}

export function fetchSemanticClusters(actor: ActorContext): Promise<SemanticClusterItem[]> {
  return requestJson<SemanticClusterItem[]>('/api/v1/ci-triage/semantic-clusters', actor);
}

export function ingestTestReport(
  actor: ActorContext,
  payload: {
    pipeline_name: string;
    branch: string;
    commit_sha: string;
    job_name: string;
    report_format: 'junit_xml' | 'playwright_json';
    content: string;
  },
): Promise<CiBuildRunItem> {
  return requestJson<CiBuildRunItem>('/api/v1/ci-triage/ingest-report', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function pullReleaseTelemetry(
  actor: ActorContext,
  releaseId: string,
  payload: {
    source: 'simulated' | 'otel_snapshot' | 'prometheus';
    total_requests?: number;
    error_requests?: number;
    p95_latency_ms?: number;
    simulated_error_rate_pct?: number;
    simulated_p95_latency_ms?: number;
    prometheus_url?: string;
  },
): Promise<ReleaseCandidateItem> {
  return requestJson<ReleaseCandidateItem>(
    `/api/v1/release-gate/releases/${releaseId}/telemetry/pull`,
    actor,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  );
}

export function fetchJobs(actor: ActorContext): Promise<BackgroundJobItem[]> {
  return requestJson<BackgroundJobItem[]>('/api/v1/jobs', actor);
}

export function enqueueJob(
  actor: ActorContext,
  payload: {
    job_type: 'canary_smoke_sweep' | 'embedding_reindex' | 'regression_suite_run';
    payload_json?: Record<string, unknown>;
  },
): Promise<BackgroundJobItem> {
  return requestJson<BackgroundJobItem>('/api/v1/jobs/enqueue', actor, {
    method: 'POST',
    body: JSON.stringify({
      job_type: payload.job_type,
      payload_json: payload.payload_json || {},
    }),
  });
}

export function dispatchGitHubWebhook(
  event: 'workflow_run' | 'deployment_status' | 'ping',
  payload: Record<string, unknown>,
): Promise<GitHubWebhookResponse> {
  return fetch('/api/v1/integrations/github/webhook', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-GitHub-Event': event,
    },
    body: JSON.stringify(payload),
  }).then(async (res) => {
    if (!res.ok) {
      throw new ApiClientError('Webhook dispatch failed', res.status);
    }
    return (await res.json()) as GitHubWebhookResponse;
  });
}

export function publishGitHubCheck(
  actor: ActorContext,
  payload: {
    repository: string;
    head_sha: string;
    release_id?: string | null;
    ci_run_id?: string | null;
    check_name?: string;
    dry_run?: boolean;
  },
): Promise<GitHubCheckPublishResponse> {
  return requestJson<GitHubCheckPublishResponse>('/api/v1/integrations/github/publish-check', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
