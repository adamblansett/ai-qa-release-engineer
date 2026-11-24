import { useState } from 'react';
import { CheckCircle2, Play, Rocket, RotateCcw, ShieldAlert, XCircle } from 'lucide-react';
import {
  createReleaseCandidate,
  requestReleasePromotion,
  requestReleaseRollback,
  runSmokeProbes,
} from '../api/client';
import type { ActorContext, RegressionRunItem, ReleaseCandidateItem } from '../types/qa';
import { StatusBadge } from './StatusBadge';

interface ReleaseGateViewProps {
  actor: ActorContext;
  releases: ReleaseCandidateItem[];
  regressionRuns: RegressionRunItem[];
  onRefresh: () => Promise<void>;
  onNotify: (text: string, isError?: boolean) => void;
}

export function ReleaseGateView({
  actor,
  releases,
  regressionRuns,
  onRefresh,
  onNotify,
}: ReleaseGateViewProps) {
  const [versionTag, setVersionTag] = useState('v2.16.0');
  const [serviceName, setServiceName] = useState('checkout-service');
  const [commitSha, setCommitSha] = useState('sha-v2160');
  const [prevVersion, setPrevVersion] = useState('v2.14.0');
  const [runbookUrl, setRunbookUrl] = useState('https://runbooks.internal/checkout/rollback');
  const [errorRate, setErrorRate] = useState('0.15');
  const [p95Latency, setP95Latency] = useState('165');
  const [regressionRunId, setRegressionRunId] = useState(regressionRuns[0]?.id || '');

  const [probeUrl, setProbeUrl] = useState('https://canary.checkout.internal/api/v1/health/ready');
  const [probeName, setProbeName] = useState('canary-ready-probe');
  const [busy, setBusy] = useState(false);

  const canMutate = actor.role !== 'viewer';

  async function handleCreateRelease(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const created = await createReleaseCandidate(actor, {
        version_tag: versionTag,
        service_name: serviceName,
        environment: 'production',
        commit_sha: commitSha,
        previous_version_tag: prevVersion,
        rollback_runbook_url: runbookUrl,
        rollback_verified: true,
        canary_error_rate_pct: Number(errorRate) || 0,
        canary_p95_latency_ms: Number(p95Latency) || 0,
        canary_traffic_pct: 15,
        regression_run_id: regressionRunId || null,
      });
      onNotify(`Registered release ${created.version_tag} (${created.decision.toUpperCase()}).`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to register release', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleRunSmokeProbe(releaseId: string) {
    setBusy(true);
    try {
      const updated = await runSmokeProbes(actor, releaseId, [
        {
          probe_name: probeName,
          target_url: probeUrl,
          http_method: 'GET',
          expected_status: 200,
          max_latency_ms: 400,
          expected_body_contains: 'ok',
          mode: 'simulated',
          simulated_status: 200,
          simulated_latency_ms: 42,
          simulated_body: '{"status":"ok"}',
        },
      ]);
      onNotify(
        `Smoke probe completed for ${updated.version_tag}: score ${updated.readiness_score}/100 (${updated.decision.toUpperCase()}).`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Smoke probe failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleRequestPromotion(releaseId: string) {
    setBusy(true);
    try {
      await requestReleasePromotion(actor, releaseId);
      onNotify('Submitted release promotion to Release Manager HITL queue.');
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Promotion request failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleRequestRollback(releaseId: string) {
    setBusy(true);
    try {
      await requestReleaseRollback(actor, releaseId);
      onNotify('Submitted emergency rollback for Release Manager approval.');
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Rollback request failed', true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <Rocket className="h-4 w-4 text-indigo-600" />
          <h2 className="text-sm font-semibold text-slate-900">
            Register Release Candidate &amp; Canary Telemetry
          </h2>
        </div>
        <form onSubmit={handleCreateRelease} className="mt-4 grid gap-3 sm:grid-cols-4">
          <input
            type="text"
            value={versionTag}
            onChange={(e) => setVersionTag(e.target.value)}
            placeholder="Version Tag"
            required
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <input
            type="text"
            value={serviceName}
            onChange={(e) => setServiceName(e.target.value)}
            placeholder="Service"
            required
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <input
            type="text"
            value={commitSha}
            onChange={(e) => setCommitSha(e.target.value)}
            placeholder="Commit SHA"
            required
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <input
            type="text"
            value={prevVersion}
            onChange={(e) => setPrevVersion(e.target.value)}
            placeholder="Rollback Target Tag"
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <input
            type="text"
            value={runbookUrl}
            onChange={(e) => setRunbookUrl(e.target.value)}
            placeholder="Rollback Runbook URL"
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs sm:col-span-2"
          />
          <input
            type="number"
            step="0.01"
            value={errorRate}
            onChange={(e) => setErrorRate(e.target.value)}
            placeholder="Error %"
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <input
            type="number"
            step="0.1"
            value={p95Latency}
            onChange={(e) => setP95Latency(e.target.value)}
            placeholder="p95 ms"
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <select
            value={regressionRunId}
            onChange={(e) => setRegressionRunId(e.target.value)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs sm:col-span-3"
          >
            <option value="">No linked regression run</option>
            {regressionRuns.map((r) => (
              <option key={r.id} value={r.id}>
                {r.suite_name} ({r.commit_sha}) — {r.status}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={busy || !canMutate}
            className="rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            Register Candidate
          </button>
        </form>
      </section>

      <section className="space-y-4">
        {releases.map((rel) => (
          <article
            key={rel.id}
            className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-base font-bold text-slate-900">
                    {rel.service_name} {rel.version_tag}
                  </h3>
                  <StatusBadge status={rel.decision} />
                  <StatusBadge status={rel.status} />
                  <span className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-700">
                    {rel.environment} · {rel.commit_sha}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-600">{rel.ai_readiness_brief}</p>
              </div>
              <div className="text-right">
                <span className="text-xs font-medium text-slate-500">Readiness Score</span>
                <p className="text-2xl font-bold text-slate-900">{rel.readiness_score}/100</p>
              </div>
            </div>

            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {rel.checklist_json.map((gate) => (
                <div
                  key={gate.gate}
                  className={`flex items-start gap-2 rounded-lg border p-2.5 text-xs ${
                    gate.passed
                      ? 'border-emerald-200 bg-emerald-50/50'
                      : 'border-rose-200 bg-rose-50/50'
                  }`}
                >
                  {gate.passed ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                  ) : (
                    <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
                  )}
                  <div>
                    <p className="font-semibold text-slate-900">{gate.label}</p>
                    <p className="mt-0.5 text-[11px] text-slate-600">{gate.detail}</p>
                  </div>
                </div>
              ))}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="text"
                  value={probeName}
                  onChange={(e) => setProbeName(e.target.value)}
                  className="rounded-md border border-slate-200 px-2.5 py-1 text-xs"
                  aria-label="Smoke Probe Name"
                />
                <input
                  type="text"
                  value={probeUrl}
                  onChange={(e) => setProbeUrl(e.target.value)}
                  className="w-72 rounded-md border border-slate-200 px-2.5 py-1 font-mono text-[11px]"
                  aria-label="Smoke Probe URL"
                />
                <button
                  type="button"
                  disabled={busy || !canMutate}
                  onClick={() => handleRunSmokeProbe(rel.id)}
                  className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                >
                  <Play className="h-3 w-3" />
                  Run Smoke Probe
                </button>
              </div>

              <div className="flex items-center gap-2">
                {canMutate && !rel.approval_id && rel.status !== 'rolled_back' && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => handleRequestPromotion(rel.id)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                  >
                    <ShieldAlert className="h-3.5 w-3.5" />
                    Request Promotion
                  </button>
                )}
                {canMutate && !rel.rollback_approval_id && rel.status !== 'rolled_back' && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => handleRequestRollback(rel.id)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-rose-300 bg-rose-50 px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-100 disabled:opacity-50"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    Request Rollback
                  </button>
                )}
              </div>
            </div>

            {rel.smoke_probes.length > 0 && (
              <div className="space-y-1">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Smoke Probe History ({rel.smoke_probes.length})
                </p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {rel.smoke_probes.map((sp) => (
                    <div
                      key={sp.id}
                      className="flex items-center justify-between rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-[11px]"
                    >
                      <span className="font-mono text-slate-800">
                        {sp.probe_name} ({sp.actual_status ?? 'ERR'}) · {sp.latency_ms}ms
                      </span>
                      <StatusBadge status={sp.passed ? 'passed' : 'failed'} />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </article>
        ))}
      </section>
    </div>
  );
}
