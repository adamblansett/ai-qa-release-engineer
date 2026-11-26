import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';

const MOCK_OVERVIEW = {
  test_suites_count: 2,
  generated_cases_count: 6,
  ci_runs_count: 6,
  ci_failed_runs_count: 4,
  flaky_tests_count: 1,
  workflow_audits_count: 2,
  regression_baselines_count: 2,
  regression_runs_count: 3,
  regression_failed_runs_count: 1,
  release_candidates_count: 2,
  go_releases_count: 1,
  blocked_releases_count: 1,
  pending_approvals_count: 1,
  audit_events_count: 4,
  audit_chain_valid: true,
  llm_provider: 'mock',
  pii_redaction_enabled: true,
};

const MOCK_APPROVALS = [
  {
    id: 'app-1',
    entity_type: 'release_promotion',
    entity_id: 'rel-1',
    action_requested: 'Promote checkout-service v2.14.0 to production',
    summary: 'Readiness 100/100 (GO). Canary error 0.12%.',
    risk_level: 'low',
    status: 'pending',
    requested_by: 'qa.engineer@acme-qa.local',
    decided_by: null,
    decision_notes: null,
    created_at: '2026-11-24T12:00:00Z',
    decided_at: null,
  },
];

function createMockFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();

    if (url.endsWith('/api/v1/health')) {
      return {
        ok: true,
        json: async () => ({
          status: 'ok',
          service: 'ai-qa-release-engineer',
          app_name: 'AI QA & Release Engineer',
          version: '0.1.0',
          environment: 'test',
          llm_provider: 'mock',
          database: 'ok',
        }),
      };
    }
    if (url.endsWith('/api/v1/overview')) {
      return { ok: true, json: async () => MOCK_OVERVIEW };
    }
    if (url.endsWith('/api/v1/testgen/suites')) {
      return {
        ok: true,
        json: async () => [
          {
            id: 'suite-1',
            name: 'Checkout & Payments API Suite',
            source_type: 'openapi',
            framework: 'playwright',
            target_base_url: 'https://staging-checkout.internal',
            spec_hash: 'abc123',
            case_count: 2,
            status: 'approved',
            generated_code: 'test("health", async () => {});',
            ai_summary: 'Deterministic summary.',
            approval_id: null,
            created_by: 'qa@acme-qa.local',
            created_at: '2026-11-24T12:00:00Z',
            cases: [
              {
                id: 'case-1',
                case_key: 'health_happy',
                title: 'GET /api/v1/health returns 200',
                category: 'happy_path',
                http_method: 'GET',
                endpoint_or_route: '/api/v1/health',
                assertions_json: ['status == 200'],
                code_snippet: 'test(...)',
                priority: 'P0',
                created_at: '2026-11-24T12:00:00Z',
              },
            ],
          },
        ],
      };
    }
    if (url.endsWith('/api/v1/ci-triage/runs')) {
      return {
        ok: true,
        json: async () => [
          {
            id: 'ci-1',
            pipeline_name: 'checkout-ci',
            branch: 'main',
            commit_sha: 'sha-v2140',
            job_name: 'backend-pytest',
            status: 'failed',
            duration_seconds: 100,
            root_cause_category: 'timeout',
            failure_signature: 'TimeoutError: waiting for redis',
            confidence: 0.92,
            remediation_summary: 'Replace fixed sleeps with readiness assertions.',
            ai_explanation: 'Timeout detected.',
            extracted_errors_json: [],
            created_at: '2026-11-24T12:00:00Z',
          },
        ],
      };
    }
    if (url.endsWith('/api/v1/ci-triage/flaky-clusters')) {
      return {
        ok: true,
        json: async () => [
          {
            test_name: 'test_checkout_discount_race',
            suite_name: 'checkout-core',
            total_runs: 5,
            pass_count: 3,
            fail_count: 2,
            pass_rate: 0.6,
            transition_count: 4,
            flakiness_score: 0.98,
            is_flaky: true,
            dominant_error_signature: 'TimeoutError',
            recommendation: 'Quarantine flaky test.',
          },
        ],
      };
    }
    if (url.endsWith('/api/v1/ci-triage/workflow-audits')) {
      return { ok: true, json: async () => [] };
    }
    if (url.endsWith('/api/v1/regression/baselines')) {
      return {
        ok: true,
        json: async () => [
          {
            id: 'bl-1',
            suite_name: 'checkout-api',
            service_name: 'checkout-service',
            gate_type: 'combined',
            version: 3,
            baseline_payload_json: { contracts: {}, snapshots: {} },
            updated_by: 'qa@acme-qa.local',
            updated_at: '2026-11-24T12:00:00Z',
          },
        ],
      };
    }
    if (url.endsWith('/api/v1/regression/runs')) {
      return {
        ok: true,
        json: async () => [
          {
            id: 'rr-1',
            baseline_id: 'bl-1',
            suite_name: 'checkout-api',
            commit_sha: 'sha-v2140',
            branch: 'main',
            gate_type: 'combined',
            status: 'passed',
            total_checks: 3,
            passed_checks: 3,
            failed_checks: 0,
            latency_p95_ms: 148,
            latency_drift_pct: 2.0,
            llm_eval_score: null,
            candidate_payload_json: {},
            diff_report_json: { contract: { breaking: [], additive: [] } },
            ai_summary: 'All checks passed.',
            baseline_promoted: false,
            promotion_approval_id: null,
            executed_by: 'ci@acme-qa.local',
            created_at: '2026-11-24T12:00:00Z',
          },
        ],
      };
    }
    if (url.endsWith('/api/v1/release-gate/releases')) {
      return {
        ok: true,
        json: async () => [
          {
            id: 'rel-1',
            version_tag: 'v2.14.0',
            service_name: 'checkout-service',
            environment: 'production',
            commit_sha: 'sha-v2140',
            previous_version_tag: 'v2.13.4',
            rollback_runbook_url: 'https://runbooks.internal/checkout',
            rollback_verified: true,
            canary_error_rate_pct: 0.12,
            canary_p95_latency_ms: 148,
            canary_traffic_pct: 25,
            regression_run_id: 'rr-1',
            readiness_score: 100,
            decision: 'go',
            status: 'pending_approval',
            checklist_json: [
              {
                gate: 'smoke_probes_green',
                label: 'Post-Deploy Smoke Probes',
                passed: true,
                detail: 'All probes passed.',
              },
            ],
            ai_readiness_brief: 'Ready for promotion.',
            approval_id: 'app-1',
            rollback_approval_id: null,
            rollback_executed_at: null,
            created_by: 'qa@acme-qa.local',
            created_at: '2026-11-24T12:00:00Z',
            smoke_probes: [],
          },
        ],
      };
    }
    if (url.endsWith('/api/v1/audit/approvals')) {
      return { ok: true, json: async () => MOCK_APPROVALS };
    }
    if (url.endsWith('/api/v1/audit/events')) {
      return { ok: true, json: async () => [] };
    }
    if (url.endsWith('/api/v1/audit/events/verify')) {
      return {
        ok: true,
        json: async () => ({
          valid: true,
          total_events: 4,
          head_hash: 'deadbeef',
          broken_sequence_no: null,
          message: 'All 4 audit events verified intact.',
        }),
      };
    }
    if (url.includes('/api/v1/audit/approvals/app-1/decide') && init?.method === 'POST') {
      return {
        ok: true,
        json: async () => ({ ...MOCK_APPROVALS[0], status: 'approved' }),
      };
    }
    if (url.endsWith('/api/v1/audit/pii/redact') && init?.method === 'POST') {
      return {
        ok: true,
        json: async () => ({
          redacted_text: 'Deploying with token [REDACTED_API_KEY]',
          findings: [{ category: 'api_key', count: 1, placeholder: '[REDACTED_API_KEY]' }],
          total_redactions: 1,
        }),
      };
    }
    if (url.includes('/api/v1/seed/demo') && init?.method === 'POST') {
      return {
        ok: true,
        json: async () => ({
          seeded: true,
          message: 'Seeded realistic QA & Release Engineering demo dataset.',
          test_suites: 2,
          ci_runs: 6,
          regression_runs: 3,
          release_candidates: 2,
          pending_approvals: 4,
        }),
      };
    }
    if (url.endsWith('/api/v1/ci-triage/semantic-clusters')) {
      return {
        ok: true,
        json: async () => [
          {
            cluster_id: 'cluster-1',
            root_cause_category: 'timeout',
            representative_signature: 'TimeoutError: waiting for redis lock',
            run_count: 2,
            avg_similarity: 0.91,
            run_ids: ['ci-1'],
            branches: ['main', 'feat/promo-stack'],
            remediation_summary: 'Replace fixed sleeps with readiness assertions.',
          },
        ],
      };
    }
    if (url.endsWith('/api/v1/jobs')) {
      return {
        ok: true,
        json: async () => [
          {
            id: 'job-1',
            job_type: 'embedding_reindex',
            execution_mode: 'inline',
            status: 'completed',
            payload_json: {},
            result_json: { reindexed_runs: 6 },
            error_message: '',
            requested_by: 'release-manager@acme-qa.local',
            created_at: '2026-11-26T07:00:00Z',
            started_at: '2026-11-26T07:00:00Z',
            completed_at: '2026-11-26T07:00:01Z',
          },
        ],
      };
    }
    if (url.endsWith('/api/v1/jobs/enqueue') && init?.method === 'POST') {
      return {
        ok: true,
        json: async () => ({
          id: 'job-2',
          job_type: 'embedding_reindex',
          execution_mode: 'inline',
          status: 'completed',
          payload_json: {},
          result_json: { reindexed_runs: 6 },
          error_message: '',
          requested_by: 'release-manager@acme-qa.local',
          created_at: '2026-11-26T07:05:00Z',
          started_at: '2026-11-26T07:05:00Z',
          completed_at: '2026-11-26T07:05:01Z',
        }),
      };
    }
    if (url.endsWith('/api/v1/auth/api-keys') && (!init?.method || init.method === 'GET')) {
      return { ok: true, json: async () => [] };
    }
    if (url.endsWith('/api/v1/auth/api-keys') && init?.method === 'POST') {
      return {
        ok: true,
        json: async () => ({
          id: 'key-1',
          name: 'github-actions-runner',
          key_prefix: 'qa_live_test123',
          role: 'qa_engineer',
          owner_email: 'ci-bot@acme-qa.local',
          created_by: 'release-manager@acme-qa.local',
          created_at: '2026-11-26T07:05:00Z',
          last_used_at: null,
          revoked_at: null,
          raw_key: 'qa_live_test123_secret_value',
        }),
      };
    }
    if (url.endsWith('/api/v1/auth/token') && init?.method === 'POST') {
      return {
        ok: true,
        json: async () => ({
          access_token: 'hdr.payload.sig',
          token_type: 'bearer',
          actor: {
            email: 'release-manager@acme-qa.local',
            role: 'release_manager',
            auth_method: 'bearer_token',
          },
        }),
      };
    }

    return { ok: false, status: 404, json: async () => ({ detail: 'Not found' }) };
  });
}

describe('AI QA & Release Engineer workspace', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders KPIs, navigates across all modules, and executes HITL & PII actions', async () => {
    const mockFetch = createMockFetch();
    vi.stubGlobal('fetch', mockFetch);

    render(<App />);

    expect(
      screen.getByRole('heading', { name: 'AI QA & Release Engineer' }),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/API Healthy \(mock\)/i)).toBeInTheDocument();
      expect(screen.getByText('2 Suites')).toBeInTheDocument();
      expect(screen.getByText('1 Flaky')).toBeInTheDocument();
      expect(screen.getByText(/Promote checkout-service v2\.14\.0/i)).toBeInTheDocument();
    });

    // Approve pending release promotion via overview HITL widget
    fireEvent.click(screen.getByRole('button', { name: /Approve/i }));
    await waitFor(() => {
      expect(screen.getByText(/Approval approved/i)).toBeInTheDocument();
    });
    const approveCall = mockFetch.mock.calls.find(
      ([u]) => typeof u === 'string' && u.includes('/approvals/app-1/decide'),
    );
    expect(approveCall).toBeTruthy();
    const headers = approveCall?.[1]?.headers as Headers;
    expect(headers.get('X-Actor-Role')).toBe('release_manager');

    // Navigate through all module tabs
    const nav = screen.getByRole('navigation', { name: 'QA & Release Modules' });
    fireEvent.click(within(nav).getByRole('button', { name: /E2E TestGen/i }));
    expect(screen.getByText(/Spec-Driven Test Synthesizer/i)).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'Checkout & Payments API Suite' }),
    ).toBeInTheDocument();

    fireEvent.click(within(nav).getByRole('button', { name: /CI\/CD Triage/i }));
    expect(screen.getByText(/Build Failure Log Triage/i)).toBeInTheDocument();
    expect(screen.getByText('test_checkout_discount_race')).toBeInTheDocument();
    expect(screen.getByText(/Semantic Failure Clusters/i)).toBeInTheDocument();

    fireEvent.click(within(nav).getByRole('button', { name: /Regression Gates/i }));
    expect(screen.getByText(/Execute Regression Gate/i)).toBeInTheDocument();

    fireEvent.click(within(nav).getByRole('button', { name: /Release Gate/i }));
    expect(screen.getByText(/checkout-service v2\.14\.0/i)).toBeInTheDocument();
    expect(screen.getByText('100/100')).toBeInTheDocument();

    fireEvent.click(within(nav).getByRole('button', { name: /Integrations & Jobs/i }));
    expect(screen.getByText(/JUnit XML \/ Playwright JSON Report Ingestion/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Run Job/i }));
    await waitFor(() => {
      expect(screen.getByText(/Job 'embedding_reindex' completed/i)).toBeInTheDocument();
    });

    fireEvent.click(within(nav).getByRole('button', { name: /Audit & Secrets/i }));
    expect(screen.getByText(/SHA-256 Immutable Audit Trail/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Scrub PII & Secrets/i }));
    await waitFor(() => {
      expect(screen.getByText(/\[REDACTED_API_KEY\]/)).toBeInTheDocument();
    });

    // Open Production Auth panel and mint a Dev JWT
    fireEvent.click(screen.getByRole('button', { name: /Auth: dev header/i }));
    fireEvent.click(screen.getByRole('button', { name: /Mint Dev JWT/i }));
    await waitFor(() => {
      expect(screen.getByText(/Minted Bearer JWT/i)).toBeInTheDocument();
    });
  });
});
