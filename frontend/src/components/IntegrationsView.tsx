import { useState } from 'react';
import {
  CheckCircle2,
  Cpu,
  FileUp,
  GitPullRequest,
  KeyRound,
  Play,
  Trash2,
  Webhook,
} from 'lucide-react';
import {
  createApiKey,
  dispatchGitHubWebhook,
  enqueueJob,
  ingestTestReport,
  publishGitHubCheck,
  revokeApiKey,
} from '../api/client';
import type {
  ActorContext,
  ActorRole,
  ApiKeyItem,
  BackgroundJobItem,
  GitHubCheckPublishResponse,
  ReleaseCandidateItem,
} from '../types/qa';
import { StatusBadge } from './StatusBadge';

interface IntegrationsViewProps {
  actor: ActorContext;
  releases: ReleaseCandidateItem[];
  jobs: BackgroundJobItem[];
  apiKeys: ApiKeyItem[];
  onRefresh: () => Promise<void>;
  onNotify: (text: string, isError?: boolean) => void;
}

const SAMPLE_JUNIT_XML = `<testsuite name="checkout-e2e" tests="2" failures="1">
  <testcase classname="tests.test_checkout" name="test_health_ok" time="0.12" />
  <testcase classname="tests.test_checkout" name="test_payment_redirect" time="1.45">
    <failure message="TimeoutError: gateway response exceeded 1200ms">TimeoutError</failure>
  </testcase>
</testsuite>`;

export function IntegrationsView({
  actor,
  releases,
  jobs,
  apiKeys,
  onRefresh,
  onNotify,
}: IntegrationsViewProps) {
  const [reportFormat, setReportFormat] = useState<'junit_xml' | 'playwright_json'>('junit_xml');
  const [reportPipeline, setReportPipeline] = useState('checkout-ci');
  const [reportBranch, setReportBranch] = useState('feat/junit-ingest');
  const [reportSha, setReportSha] = useState('sha-junit-01');
  const [reportContent, setReportContent] = useState(SAMPLE_JUNIT_XML);

  const [repoSlug, setRepoSlug] = useState('adamblansett/ai-qa-release-engineer');
  const [checkSha, setCheckSha] = useState(releases[0]?.commit_sha || 'sha-v2140');
  const [selectedReleaseId, setSelectedReleaseId] = useState(releases[0]?.id || '');
  const [checkPreview, setCheckPreview] = useState<GitHubCheckPublishResponse | null>(null);

  const [jobType, setJobType] = useState<
    'canary_smoke_sweep' | 'embedding_reindex' | 'regression_suite_run'
  >('embedding_reindex');

  const [keyName, setKeyName] = useState('github-actions-runner');
  const [keyRole, setKeyRole] = useState<ActorRole>('qa_engineer');
  const [keyOwner, setKeyOwner] = useState('ci-bot@acme-qa.local');
  const [newRawKey, setNewRawKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const canMutate = actor.role !== 'viewer';
  const canManageKeys = actor.role === 'release_manager' || actor.role === 'admin';

  async function handleIngestReport(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await ingestTestReport(actor, {
        pipeline_name: reportPipeline,
        branch: reportBranch,
        commit_sha: reportSha,
        job_name: reportFormat === 'junit_xml' ? 'junit-suite' : 'playwright-json',
        report_format: reportFormat,
        content: reportContent,
      });
      onNotify(`Ingested ${reportFormat} report -> ${res.status} (${res.root_cause_category}).`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Report ingestion failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleSimulateWebhook() {
    setBusy(true);
    try {
      const res = await dispatchGitHubWebhook('workflow_run', {
        repository: { full_name: repoSlug },
        workflow_run: {
          name: 'CI Nightly E2E',
          conclusion: 'failure',
          head_branch: 'main',
          head_sha: checkSha,
          log_excerpt: 'TimeoutError: waiting for canary readiness timed out after 5000ms',
        },
      });
      onNotify(`GitHub webhook ${res.event} processed (${res.action_taken}).`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Webhook dispatch failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handlePublishCheck(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await publishGitHubCheck(actor, {
        repository: repoSlug,
        head_sha: checkSha,
        release_id: selectedReleaseId || null,
        dry_run: true,
      });
      setCheckPreview(res);
      onNotify(`Prepared PR Check Run (${res.conclusion}) for ${res.repository}.`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'PR Check Run failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleEnqueueJob() {
    setBusy(true);
    try {
      const res = await enqueueJob(actor, {
        job_type: jobType,
        payload_json:
          jobType === 'canary_smoke_sweep' && selectedReleaseId
            ? { release_id: selectedReleaseId }
            : {},
      });
      onNotify(`Job '${res.job_type}' ${res.status} (${res.execution_mode}).`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Job enqueue failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateKey(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const created = await createApiKey(actor, {
        name: keyName,
        role: keyRole,
        owner_email: keyOwner,
      });
      setNewRawKey(created.raw_key);
      onNotify(`Provisioned API key '${created.name}' (${created.key_prefix}...).`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'API key creation failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleRevokeKey(keyId: string) {
    setBusy(true);
    try {
      await revokeApiKey(actor, keyId);
      onNotify('Revoked API key.');
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Revocation failed', true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <FileUp className="h-4 w-4 text-indigo-600" />
              <h2 className="text-sm font-semibold text-slate-900">
                JUnit XML / Playwright JSON Report Ingestion
              </h2>
            </div>
            <select
              aria-label="Report Format"
              value={reportFormat}
              onChange={(e) =>
                setReportFormat(e.target.value as 'junit_xml' | 'playwright_json')
              }
              className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs"
            >
              <option value="junit_xml">JUnit XML</option>
              <option value="playwright_json">Playwright JSON</option>
            </select>
          </div>
          <form onSubmit={handleIngestReport} className="mt-4 space-y-3">
            <div className="grid grid-cols-3 gap-2">
              <input
                type="text"
                value={reportPipeline}
                onChange={(e) => setReportPipeline(e.target.value)}
                placeholder="Pipeline"
                required
                className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
              />
              <input
                type="text"
                value={reportBranch}
                onChange={(e) => setReportBranch(e.target.value)}
                placeholder="Branch"
                required
                className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
              />
              <input
                type="text"
                value={reportSha}
                onChange={(e) => setReportSha(e.target.value)}
                placeholder="Commit SHA"
                required
                className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
              />
            </div>
            <textarea
              rows={6}
              value={reportContent}
              onChange={(e) => setReportContent(e.target.value)}
              required
              className="w-full rounded-lg border border-slate-200 p-2.5 font-mono text-[11px] focus:border-indigo-400 focus:outline-none"
            />
            <button
              type="submit"
              disabled={busy || !canMutate}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              Ingest Test Report
            </button>
          </form>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <GitPullRequest className="h-4 w-4 text-emerald-600" />
              <h2 className="text-sm font-semibold text-slate-900">
                GitHub Actions Webhooks &amp; PR Check Publisher
              </h2>
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={handleSimulateWebhook}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100"
            >
              <Webhook className="h-3.5 w-3.5" />
              Test Webhook Event
            </button>
          </div>

          <form onSubmit={handlePublishCheck} className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <input
                type="text"
                value={repoSlug}
                onChange={(e) => setRepoSlug(e.target.value)}
                placeholder="owner/repo"
                required
                className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
              />
              <input
                type="text"
                value={checkSha}
                onChange={(e) => setCheckSha(e.target.value)}
                placeholder="Commit SHA"
                required
                className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
              />
            </div>
            <select
              value={selectedReleaseId}
              onChange={(e) => setSelectedReleaseId(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs"
            >
              <option value="">No specific release linked</option>
              {releases.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.service_name} {r.version_tag} ({r.decision.toUpperCase()})
                </option>
              ))}
            </select>
            <button
              type="submit"
              disabled={busy || !canMutate}
              className="rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Publish PR Check Run (Dry-Run)
            </button>
          </form>

          {checkPreview && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-900">{checkPreview.title}</span>
                <StatusBadge
                  status={checkPreview.conclusion === 'success' ? 'passed' : 'warning'}
                />
              </div>
              <pre className="max-h-32 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-slate-700">
                {checkPreview.summary_markdown}
              </pre>
            </div>
          )}
        </section>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Cpu className="h-4 w-4 text-indigo-600" />
              <h2 className="text-sm font-semibold text-slate-900">
                Background Worker Queue ({jobs.length})
              </h2>
            </div>
            <div className="flex items-center gap-2">
              <select
                aria-label="Background Job Type"
                value={jobType}
                onChange={(e) =>
                  setJobType(
                    e.target.value as
                      | 'canary_smoke_sweep'
                      | 'embedding_reindex'
                      | 'regression_suite_run',
                  )
                }
                className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs"
              >
                <option value="embedding_reindex">Reindex Failure Embeddings</option>
                <option value="canary_smoke_sweep">Canary Smoke Sweep</option>
                <option value="regression_suite_run">Scheduled Regression Suite</option>
              </select>
              <button
                type="button"
                disabled={busy || !canMutate}
                onClick={handleEnqueueJob}
                className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                <Play className="h-3 w-3" />
                Run Job
              </button>
            </div>
          </div>

          <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
            {jobs.map((job) => (
              <div
                key={job.id}
                className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono font-semibold text-slate-900">{job.job_type}</span>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] text-slate-500">{job.execution_mode}</span>
                    <StatusBadge
                      status={
                        job.status === 'completed'
                          ? 'passed'
                          : job.status === 'failed'
                          ? 'failed'
                          : 'evaluating'
                      }
                    />
                  </div>
                </div>
                <p className="mt-1 font-mono text-[11px] text-slate-600">
                  {Object.keys(job.result_json).length > 0
                    ? JSON.stringify(job.result_json)
                    : job.error_message || 'Queued for worker'}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
          <div className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-amber-600" />
            <h2 className="text-sm font-semibold text-slate-900">
              Production API Keys ({apiKeys.length})
            </h2>
          </div>

          {!canManageKeys ? (
            <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
              API key provisioning and revocation require <strong>Release Manager</strong> or{' '}
              <strong>Admin</strong> role.
            </p>
          ) : (
            <>
              <form onSubmit={handleCreateKey} className="grid grid-cols-3 gap-2">
                <input
                  type="text"
                  value={keyName}
                  onChange={(e) => setKeyName(e.target.value)}
                  placeholder="Key Name"
                  required
                  className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
                />
                <input
                  type="email"
                  value={keyOwner}
                  onChange={(e) => setKeyOwner(e.target.value)}
                  placeholder="Owner Email"
                  required
                  className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
                />
                <div className="flex gap-1.5">
                  <select
                    value={keyRole}
                    onChange={(e) => setKeyRole(e.target.value as ActorRole)}
                    className="flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs"
                  >
                    <option value="qa_engineer">QA</option>
                    <option value="release_manager">Manager</option>
                    <option value="viewer">Viewer</option>
                  </select>
                  <button
                    type="submit"
                    disabled={busy}
                    className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
                  >
                    Mint
                  </button>
                </div>
              </form>

              {newRawKey && (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs">
                  <div className="flex items-center gap-1.5 font-semibold text-emerald-900">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    One-Time API Key Secret (copy now):
                  </div>
                  <p className="mt-1 break-all font-mono text-[11px] text-emerald-950">
                    {newRawKey}
                  </p>
                </div>
              )}

              <div className="max-h-48 space-y-2 overflow-y-auto pr-1">
                {apiKeys.map((k) => (
                  <div
                    key={k.id}
                    className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs"
                  >
                    <div>
                      <span className="font-semibold text-slate-900">{k.name}</span>
                      <span className="ml-2 font-mono text-[11px] text-slate-500">
                        {k.key_prefix}... · {k.role}
                      </span>
                    </div>
                    {k.revoked_at ? (
                      <StatusBadge status="rejected" />
                    ) : (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => handleRevokeKey(k.id)}
                        className="inline-flex items-center gap-1 rounded border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] font-semibold text-rose-700 hover:bg-rose-100"
                      >
                        <Trash2 className="h-3 w-3" />
                        Revoke
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
