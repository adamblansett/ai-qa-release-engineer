import { useState } from 'react';
import {
  CheckCircle2,
  Database,
  FlaskConical,
  GitBranch,
  Rocket,
  ShieldCheck,
  Terminal,
  XCircle,
} from 'lucide-react';
import { decideApproval } from '../api/client';
import type { ActorContext, ApprovalRequestItem, OverviewSummary } from '../types/qa';
import { StatusBadge } from './StatusBadge';

interface OverviewViewProps {
  actor: ActorContext;
  overview: OverviewSummary | null;
  approvals: ApprovalRequestItem[];
  onNavigate: (tab: string) => void;
  onLoadDemo: () => void;
  onRefresh: () => Promise<void>;
  onNotify: (text: string, isError?: boolean) => void;
  busy: boolean;
}

export function OverviewView({
  actor,
  overview,
  approvals,
  onNavigate,
  onLoadDemo,
  onRefresh,
  onNotify,
  busy,
}: OverviewViewProps) {
  const [notesById, setNotesById] = useState<Record<string, string>>({});
  const [decidingId, setDecidingId] = useState<string | null>(null);

  const pendingApprovals = approvals.filter((a) => a.status === 'pending');
  const canApprove = actor.role === 'release_manager' || actor.role === 'admin';
  const isEmpty = overview !== null && overview.test_suites_count === 0 && overview.ci_runs_count === 0;

  async function handleDecision(approvalId: string, decision: 'approved' | 'rejected') {
    setDecidingId(approvalId);
    try {
      const notes = notesById[approvalId] || `${decision} via executive overview`;
      await decideApproval(actor, approvalId, decision, notes);
      onNotify(`Approval ${decision} (${approvalId.slice(0, 8)}).`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Approval action failed', true);
    } finally {
      setDecidingId(null);
    }
  }

  return (
    <div className="space-y-6">
      {isEmpty && (
        <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-indigo-200 bg-indigo-50/70 p-5">
          <div>
            <h2 className="text-sm font-semibold text-indigo-950">
              Initialize QA &amp; Release Demo Workspace
            </h2>
            <p className="mt-1 text-xs text-indigo-800">
              Load realistic OpenAPI/Playwright suites, flaky CI test history, contract/LLM-eval
              regression runs, and release candidates with pending human sign-off gates.
            </p>
          </div>
          <button
            type="button"
            onClick={onLoadDemo}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
          >
            <Database className="h-4 w-4" />
            {busy ? 'Loading Demo...' : 'Load Demo Data'}
          </button>
        </section>
      )}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <button
          type="button"
          onClick={() => onNavigate('testgen')}
          className="rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-indigo-300"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-500">E2E TestGen</span>
            <FlaskConical className="h-4 w-4 text-indigo-600" />
          </div>
          <p className="mt-2 text-2xl font-bold text-slate-900">
            {overview?.test_suites_count ?? 0} Suites
          </p>
          <p className="mt-1 text-xs text-slate-600">
            {overview?.generated_cases_count ?? 0} synthesized cases
          </p>
        </button>

        <button
          type="button"
          onClick={() => onNavigate('ci_triage')}
          className="rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-indigo-300"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-500">CI/CD Health</span>
            <Terminal className="h-4 w-4 text-amber-600" />
          </div>
          <p className="mt-2 text-2xl font-bold text-slate-900">
            {overview?.flaky_tests_count ?? 0} Flaky
          </p>
          <p className="mt-1 text-xs text-slate-600">
            {overview?.ci_failed_runs_count ?? 0}/{overview?.ci_runs_count ?? 0} failing jobs ·{' '}
            {overview?.workflow_audits_count ?? 0} YAML audits
          </p>
        </button>

        <button
          type="button"
          onClick={() => onNavigate('regression')}
          className="rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-indigo-300"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-500">Regression Gates</span>
            <GitBranch className="h-4 w-4 text-emerald-600" />
          </div>
          <p className="mt-2 text-2xl font-bold text-slate-900">
            {overview?.regression_runs_count ?? 0} Runs
          </p>
          <p className="mt-1 text-xs text-slate-600">
            {overview?.regression_baselines_count ?? 0} baselines ·{' '}
            {overview?.regression_failed_runs_count ?? 0} failed
          </p>
        </button>

        <button
          type="button"
          onClick={() => onNavigate('release_gate')}
          className="rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-indigo-300"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-500">Release Gate</span>
            <Rocket className="h-4 w-4 text-indigo-600" />
          </div>
          <p className="mt-2 text-2xl font-bold text-slate-900">
            {overview?.go_releases_count ?? 0} GO / {overview?.blocked_releases_count ?? 0} NO-GO
          </p>
          <p className="mt-1 text-xs text-slate-600">
            {overview?.pending_approvals_count ?? 0} HITL gates pending
          </p>
        </button>
      </section>

      <section className="grid gap-5 lg:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm lg:col-span-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900">
              Pending Human-in-the-Loop Approvals ({pendingApprovals.length})
            </h2>
            <button
              type="button"
              onClick={() => onNavigate('audit')}
              className="text-xs font-semibold text-indigo-600 hover:underline"
            >
              View Audit &amp; Queue
            </button>
          </div>
          {!canApprove && pendingApprovals.length > 0 && (
            <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Active role <strong>{actor.role}</strong> is read/propose-only for HITL gates. Switch
              role to <strong>Release Manager</strong> to approve or reject.
            </p>
          )}
          {pendingApprovals.length === 0 ? (
            <p className="mt-4 text-xs text-slate-500">
              No pending release promotions, rollbacks, or baseline updates.
            </p>
          ) : (
            <ul className="mt-4 space-y-3">
              {pendingApprovals.map((app) => (
                <li
                  key={app.id}
                  className="rounded-lg border border-slate-200 bg-slate-50/70 p-3.5"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-semibold text-slate-900">
                          {app.action_requested}
                        </span>
                        <StatusBadge status={app.risk_level} />
                        <StatusBadge status={app.entity_type} />
                      </div>
                      <p className="mt-1 text-xs text-slate-600">{app.summary}</p>
                      <p className="mt-1 text-[11px] text-slate-500">
                        Requested by {app.requested_by}
                      </p>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <input
                      type="text"
                      placeholder="Decision notes..."
                      value={notesById[app.id] || ''}
                      onChange={(e) =>
                        setNotesById((prev) => ({ ...prev, [app.id]: e.target.value }))
                      }
                      className="min-w-[200px] flex-1 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs focus:border-indigo-400 focus:outline-none"
                    />
                    <button
                      type="button"
                      disabled={!canApprove || decidingId === app.id}
                      onClick={() => handleDecision(app.id, 'approved')}
                      className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-40"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      Approve
                    </button>
                    <button
                      type="button"
                      disabled={!canApprove || decidingId === app.id}
                      onClick={() => handleDecision(app.id, 'rejected')}
                      className="inline-flex items-center gap-1 rounded-md bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-40"
                    >
                      <XCircle className="h-3.5 w-3.5" />
                      Reject
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-600" />
            <h2 className="text-sm font-semibold text-slate-900">Governance &amp; LLM Guardrails</h2>
          </div>
          <dl className="mt-4 space-y-3 text-xs">
            <div className="flex items-center justify-between border-b border-slate-100 pb-2">
              <dt className="text-slate-500">Audit SHA-256 Chain</dt>
              <dd>
                <StatusBadge status={overview?.audit_chain_valid ? 'valid' : 'failed'} />
              </dd>
            </div>
            <div className="flex items-center justify-between border-b border-slate-100 pb-2">
              <dt className="text-slate-500">Recorded Audit Events</dt>
              <dd className="font-semibold text-slate-900">{overview?.audit_events_count ?? 0}</dd>
            </div>
            <div className="flex items-center justify-between border-b border-slate-100 pb-2">
              <dt className="text-slate-500">Active LLM Provider</dt>
              <dd className="font-mono font-semibold text-indigo-700">
                {overview?.llm_provider ?? 'mock'}
              </dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-slate-500">Cloud PII &amp; Secret Redaction</dt>
              <dd>
                <StatusBadge status={overview?.pii_redaction_enabled ? 'approved' : 'warning'} />
              </dd>
            </div>
          </dl>
        </div>
      </section>
    </div>
  );
}
