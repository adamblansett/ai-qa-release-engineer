import { useState } from 'react';
import { CheckCircle2, Lock, ShieldCheck, XCircle } from 'lucide-react';
import { decideApproval, redactPiiText, verifyAuditChain } from '../api/client';
import type {
  ActorContext,
  ApprovalRequestItem,
  AuditChainVerify,
  AuditEventItem,
  PiiRedactResult,
} from '../types/qa';
import { StatusBadge } from './StatusBadge';

interface AuditLogViewProps {
  actor: ActorContext;
  approvals: ApprovalRequestItem[];
  events: AuditEventItem[];
  chainStatus: AuditChainVerify | null;
  onChainVerified: (result: AuditChainVerify) => void;
  onRefresh: () => Promise<void>;
  onNotify: (text: string, isError?: boolean) => void;
}

export function AuditLogView({
  actor,
  approvals,
  events,
  chainStatus,
  onChainVerified,
  onRefresh,
  onNotify,
}: AuditLogViewProps) {
  const [sampleText, setSampleText] = useState(
    'Deploying with token ghp_AbCdEfGhIjKlMnOpQrStUvWxYz123456 and db postgres://admin:s3cr3t@db.internal:5432/prod for oncall@acme-qa.local',
  );
  const [redactResult, setRedactResult] = useState<PiiRedactResult | null>(null);
  const [busy, setBusy] = useState(false);

  const canApprove = actor.role === 'release_manager' || actor.role === 'admin';

  async function handleVerifyChain() {
    setBusy(true);
    try {
      const res = await verifyAuditChain(actor);
      onChainVerified(res);
      onNotify(res.message, !res.valid);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Chain verification failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleTestScrubber(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await redactPiiText(actor, sampleText);
      setRedactResult(res);
      onNotify(`Scrubbed ${res.total_redactions} sensitive PII/secret token(s).`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Redaction test failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleDecision(approvalId: string, decision: 'approved' | 'rejected') {
    setBusy(true);
    try {
      await decideApproval(actor, approvalId, decision, `${decision} via audit governance console`);
      onNotify(`Approval ${decision}.`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Decision failed', true);
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
              <ShieldCheck className="h-4 w-4 text-emerald-600" />
              <h2 className="text-sm font-semibold text-slate-900">
                SHA-256 Immutable Audit Trail
              </h2>
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={handleVerifyChain}
              className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-800 hover:bg-emerald-100"
            >
              Verify Chain
            </button>
          </div>
          {chainStatus && (
            <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-900">{chainStatus.message}</span>
                <StatusBadge status={chainStatus.valid ? 'valid' : 'failed'} />
              </div>
              <p className="mt-1 truncate font-mono text-[11px] text-slate-500">
                Head Hash: {chainStatus.head_hash}
              </p>
            </div>
          )}

          <div className="mt-4 max-h-72 space-y-2 overflow-y-auto pr-1">
            {events.map((ev) => (
              <div
                key={ev.id}
                className="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono font-semibold text-slate-900">
                    #{ev.sequence_no} {ev.event_type}
                  </span>
                  <span className="text-[11px] text-slate-500">
                    {ev.actor_email} ({ev.actor_role})
                  </span>
                </div>
                <p className="mt-0.5 truncate font-mono text-[10px] text-slate-500">
                  hash: {ev.event_hash}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <Lock className="h-4 w-4 text-indigo-600" />
            <h2 className="text-sm font-semibold text-slate-900">
              Outbound Cloud PII &amp; CI Secret Scrubber
            </h2>
          </div>
          <form onSubmit={handleTestScrubber} className="mt-3 space-y-3">
            <textarea
              rows={4}
              value={sampleText}
              onChange={(e) => setSampleText(e.target.value)}
              className="w-full rounded-lg border border-slate-200 p-2.5 font-mono text-[11px] focus:border-indigo-400 focus:outline-none"
              aria-label="Sensitive Log or Prompt Text"
            />
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700"
            >
              Scrub PII &amp; Secrets
            </button>
          </form>

          {redactResult && (
            <div className="mt-4 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-900">
                  Redacted Output ({redactResult.total_redactions} redaction(s))
                </span>
                <StatusBadge status="approved" />
              </div>
              <pre className="whitespace-pre-wrap font-mono text-[11px] text-slate-800">
                {redactResult.redacted_text}
              </pre>
            </div>
          )}
        </section>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-900">
          All HITL Approval Gates ({approvals.length})
        </h2>
        <div className="mt-3 space-y-2">
          {approvals.map((app) => (
            <div
              key={app.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs"
            >
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-slate-900">{app.action_requested}</span>
                  <StatusBadge status={app.status} />
                  <StatusBadge status={app.risk_level} />
                </div>
                <p className="mt-1 text-slate-600">{app.summary}</p>
                {app.decided_by && (
                  <p className="mt-0.5 text-[11px] text-slate-500">
                    Decided by {app.decided_by}: {app.decision_notes}
                  </p>
                )}
              </div>
              {app.status === 'pending' && canApprove && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => handleDecision(app.id, 'approved')}
                    className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700"
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Approve
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => handleDecision(app.id, 'rejected')}
                    className="inline-flex items-center gap-1 rounded-md bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-700"
                  >
                    <XCircle className="h-3.5 w-3.5" />
                    Reject
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
