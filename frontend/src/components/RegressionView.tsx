import { useState } from 'react';
import { ArrowUpCircle, GitBranch, Play } from 'lucide-react';
import { executeRegressionRun, proposeBaselinePromotion } from '../api/client';
import type {
  ActorContext,
  RegressionBaselineItem,
  RegressionRunItem,
} from '../types/qa';
import { StatusBadge } from './StatusBadge';

interface RegressionViewProps {
  actor: ActorContext;
  baselines: RegressionBaselineItem[];
  runs: RegressionRunItem[];
  onRefresh: () => Promise<void>;
  onNotify: (text: string, isError?: boolean) => void;
}

export function RegressionView({
  actor,
  baselines,
  runs,
  onRefresh,
  onNotify,
}: RegressionViewProps) {
  const [suiteName, setSuiteName] = useState(baselines[0]?.suite_name || 'checkout-api');
  const [commitSha, setCommitSha] = useState('sha-cand-101');
  const [branch, setBranch] = useState('feat/gate-check');
  const [latencyP95, setLatencyP95] = useState('150');
  const [payloadText, setPayloadText] = useState(
    JSON.stringify(
      baselines[0]?.baseline_payload_json || {
        contracts: {},
        snapshots: {},
      },
      null,
      2,
    ),
  );
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const canMutate = actor.role !== 'viewer';
  const activeRun = runs.find((r) => r.id === selectedRunId) || runs[0] || null;

  function handleSelectBaselineSuite(name: string) {
    setSuiteName(name);
    const match = baselines.find((b) => b.suite_name === name);
    if (match) {
      setPayloadText(JSON.stringify(match.baseline_payload_json, null, 2));
    }
  }

  async function handleRunRegression(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const parsed = JSON.parse(payloadText) as Record<string, unknown>;
      const res = await executeRegressionRun(actor, {
        suite_name: suiteName,
        commit_sha: commitSha,
        branch,
        latency_p95_ms: Number(latencyP95) || 0,
        candidate_payload_json: parsed,
      });
      setSelectedRunId(res.id);
      onNotify(
        `Regression run '${res.suite_name}' completed: ${res.status.toUpperCase()} (${res.passed_checks}/${res.total_checks})`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Regression run failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleProposePromotion(runId: string) {
    setBusy(true);
    try {
      await proposeBaselinePromotion(actor, runId);
      onNotify('Proposed candidate outputs for HITL baseline promotion.');
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Baseline promotion proposal failed', true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm lg:col-span-2">
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-indigo-600" />
          <h2 className="text-sm font-semibold text-slate-900">Execute Regression Gate</h2>
        </div>

        <form onSubmit={handleRunRegression} className="mt-4 space-y-3">
          <div>
            <label className="block text-xs font-medium text-slate-700">Baseline Suite</label>
            <select
              value={suiteName}
              onChange={(e) => handleSelectBaselineSuite(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs focus:border-indigo-400 focus:outline-none"
            >
              {baselines.map((b) => (
                <option key={b.id} value={b.suite_name}>
                  {b.suite_name} (v{b.version} · {b.gate_type})
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <input
              type="text"
              value={commitSha}
              onChange={(e) => setCommitSha(e.target.value)}
              placeholder="Commit SHA"
              required
              className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
            />
            <input
              type="text"
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              placeholder="Branch"
              required
              className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
            />
            <input
              type="number"
              step="0.1"
              value={latencyP95}
              onChange={(e) => setLatencyP95(e.target.value)}
              placeholder="p95 ms"
              className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700">
              Candidate Payload JSON (contracts / snapshots / llm_eval_outputs)
            </label>
            <textarea
              rows={10}
              value={payloadText}
              onChange={(e) => setPayloadText(e.target.value)}
              required
              className="mt-1 w-full rounded-lg border border-slate-200 p-2.5 font-mono text-[11px] focus:border-indigo-400 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={busy || !canMutate || baselines.length === 0}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            <Play className="h-3.5 w-3.5" />
            Run Contract / Snapshot / Eval Gate
          </button>
        </form>
      </section>

      <section className="space-y-4 lg:col-span-3">
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-900">
            Active Baselines ({baselines.length}) &amp; Recent Runs ({runs.length})
          </h2>
          <div className="mt-3 space-y-2">
            {runs.map((run) => (
              <button
                key={run.id}
                type="button"
                onClick={() => setSelectedRunId(run.id)}
                className={`w-full rounded-lg border p-3 text-left text-xs transition ${
                  activeRun?.id === run.id
                    ? 'border-indigo-500 bg-indigo-50/50'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold text-slate-900">
                    {run.suite_name} · {run.commit_sha}
                  </span>
                  <div className="flex items-center gap-1.5">
                    {run.baseline_promoted && <StatusBadge status="approved" />}
                    <StatusBadge status={run.status} />
                  </div>
                </div>
                <p className="mt-1 text-[11px] text-slate-600">
                  Checks: {run.passed_checks}/{run.total_checks} passed · Latency drift:{' '}
                  {run.latency_drift_pct > 0 ? `+${run.latency_drift_pct}%` : `${run.latency_drift_pct}%`}
                  {run.llm_eval_score !== null && ` · Eval score: ${run.llm_eval_score}`}
                </p>
              </button>
            ))}
          </div>
        </div>

        {activeRun && (
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">
                  Diff &amp; Rubric Inspector — {activeRun.suite_name}
                </h3>
                <p className="mt-0.5 text-xs text-slate-600">{activeRun.ai_summary}</p>
              </div>
              {canMutate && !activeRun.baseline_promoted && !activeRun.promotion_approval_id && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => handleProposePromotion(activeRun.id)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-100"
                >
                  <ArrowUpCircle className="h-3.5 w-3.5" />
                  Propose Baseline Promotion
                </button>
              )}
            </div>
            <pre className="max-h-64 overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] text-slate-100">
              {JSON.stringify(activeRun.diff_report_json, null, 2)}
            </pre>
          </div>
        )}
      </section>
    </div>
  );
}
