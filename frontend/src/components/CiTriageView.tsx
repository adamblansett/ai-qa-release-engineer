import { useState } from 'react';
import { AlertTriangle, FileCheck2, Terminal } from 'lucide-react';
import { analyzeCiLog, auditWorkflowYaml } from '../api/client';
import type {
  ActorContext,
  CiBuildRunItem,
  FlakyClusterItem,
  WorkflowAuditItem,
} from '../types/qa';
import { StatusBadge } from './StatusBadge';

interface CiTriageViewProps {
  actor: ActorContext;
  runs: CiBuildRunItem[];
  flakyClusters: FlakyClusterItem[];
  workflowAudits: WorkflowAuditItem[];
  onRefresh: () => Promise<void>;
  onNotify: (text: string, isError?: boolean) => void;
}

const SAMPLE_WORKFLOW = `name: Release Check
on:
  pull_request:
    branches: [main]
permissions:
  contents: read
concurrency:
  group: release-check-\${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - run: npm ci && npm test`;

export function CiTriageView({
  actor,
  runs,
  flakyClusters,
  workflowAudits,
  onRefresh,
  onNotify,
}: CiTriageViewProps) {
  const [pipelineName, setPipelineName] = useState('checkout-ci');
  const [branch, setBranch] = useState('feat/payment-retry');
  const [commitSha, setCommitSha] = useState('sha-abc123');
  const [jobName, setJobName] = useState('pytest-e2e');
  const [rawLog, setRawLog] = useState(
    'FAILED tests/test_checkout.py::test_payment_timeout - TimeoutError: waiting for gateway timed out after 5000ms',
  );

  const [wfName, setWfName] = useState('PR Release Check');
  const [wfFilename, setWfFilename] = useState('.github/workflows/release-check.yml');
  const [wfYaml, setWfYaml] = useState(SAMPLE_WORKFLOW);
  const [busy, setBusy] = useState(false);

  const canMutate = actor.role !== 'viewer';

  async function handleAnalyzeLog(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await analyzeCiLog(actor, {
        pipeline_name: pipelineName,
        branch,
        commit_sha: commitSha,
        job_name: jobName,
        raw_log: rawLog,
      });
      onNotify(`Triaged CI run (${res.status}) -> ${res.root_cause_category}`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'CI triage failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleAuditWorkflow(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await auditWorkflowYaml(actor, {
        workflow_name: wfName,
        filename: wfFilename,
        workflow_yaml: wfYaml,
      });
      onNotify(`Workflow audit score: ${res.score}/100 (${res.passed ? 'passed' : 'failed'})`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Workflow audit failed', true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <Terminal className="h-4 w-4 text-indigo-600" />
            <h2 className="text-sm font-semibold text-slate-900">Build Failure Log Triage</h2>
          </div>
          <form onSubmit={handleAnalyzeLog} className="mt-4 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <input
                type="text"
                value={pipelineName}
                onChange={(e) => setPipelineName(e.target.value)}
                placeholder="Pipeline"
                required
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs focus:border-indigo-400 focus:outline-none"
              />
              <input
                type="text"
                value={jobName}
                onChange={(e) => setJobName(e.target.value)}
                placeholder="Job Name"
                required
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs focus:border-indigo-400 focus:outline-none"
              />
              <input
                type="text"
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
                placeholder="Branch"
                required
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs focus:border-indigo-400 focus:outline-none"
              />
              <input
                type="text"
                value={commitSha}
                onChange={(e) => setCommitSha(e.target.value)}
                placeholder="Commit SHA"
                required
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs focus:border-indigo-400 focus:outline-none"
              />
            </div>
            <textarea
              rows={5}
              value={rawLog}
              onChange={(e) => setRawLog(e.target.value)}
              required
              className="w-full rounded-lg border border-slate-200 p-2.5 font-mono text-[11px] focus:border-indigo-400 focus:outline-none"
            />
            <button
              type="submit"
              disabled={busy || !canMutate}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              Analyze CI Log
            </button>
          </form>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <FileCheck2 className="h-4 w-4 text-emerald-600" />
            <h2 className="text-sm font-semibold text-slate-900">
              GitHub Actions Workflow Validator
            </h2>
          </div>
          <form onSubmit={handleAuditWorkflow} className="mt-4 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <input
                type="text"
                value={wfName}
                onChange={(e) => setWfName(e.target.value)}
                placeholder="Workflow Name"
                required
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs focus:border-indigo-400 focus:outline-none"
              />
              <input
                type="text"
                value={wfFilename}
                onChange={(e) => setWfFilename(e.target.value)}
                placeholder="Filename"
                required
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs focus:border-indigo-400 focus:outline-none"
              />
            </div>
            <textarea
              rows={5}
              value={wfYaml}
              onChange={(e) => setWfYaml(e.target.value)}
              required
              className="w-full rounded-lg border border-slate-200 p-2.5 font-mono text-[11px] focus:border-indigo-400 focus:outline-none"
            />
            <button
              type="submit"
              disabled={busy || !canMutate}
              className="rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Validate Workflow YAML
            </button>
          </form>
        </section>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-600" />
          <h2 className="text-sm font-semibold text-slate-900">
            Flaky-Test Clusters ({flakyClusters.filter((c) => c.is_flaky).length} quarantined)
          </h2>
        </div>
        {flakyClusters.length === 0 ? (
          <p className="mt-3 text-xs text-slate-500">No historical test records recorded yet.</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="pb-2 pr-3 font-medium">Test Name</th>
                  <th className="pb-2 pr-3 font-medium">Pass / Fail</th>
                  <th className="pb-2 pr-3 font-medium">Pass Rate</th>
                  <th className="pb-2 pr-3 font-medium">Flips</th>
                  <th className="pb-2 pr-3 font-medium">Score</th>
                  <th className="pb-2 pr-3 font-medium">Status</th>
                  <th className="pb-2 font-medium">Recommendation</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {flakyClusters.map((c) => (
                  <tr key={c.test_name}>
                    <td className="py-2 pr-3 font-mono text-[11px] text-slate-900">
                      {c.test_name}
                    </td>
                    <td className="py-2 pr-3">
                      {c.pass_count} / {c.fail_count}
                    </td>
                    <td className="py-2 pr-3">{Math.round(c.pass_rate * 100)}%</td>
                    <td className="py-2 pr-3">{c.transition_count}</td>
                    <td className="py-2 pr-3 font-semibold">{c.flakiness_score.toFixed(2)}</td>
                    <td className="py-2 pr-3">
                      <StatusBadge
                        status={c.is_flaky ? 'flaky' : c.fail_count > 0 && c.pass_count === 0 ? 'failed' : 'stable'}
                      />
                    </td>
                    <td className="py-2 text-slate-600">{c.recommendation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-900">
            Analyzed CI Runs ({runs.length})
          </h2>
          <div className="mt-3 max-h-80 space-y-2.5 overflow-y-auto pr-1">
            {runs.map((run) => (
              <div key={run.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold text-slate-900">
                    {run.pipeline_name} · {run.job_name}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <StatusBadge status={run.root_cause_category} />
                    <StatusBadge status={run.status} />
                  </div>
                </div>
                <p className="mt-1 font-mono text-[11px] text-slate-500">
                  {run.branch} @ {run.commit_sha} · {Math.round(run.confidence * 100)}% confidence
                </p>
                <p className="mt-1 text-slate-700">{run.remediation_summary}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-900">
            Workflow Security &amp; Reliability Audits ({workflowAudits.length})
          </h2>
          <div className="mt-3 max-h-80 space-y-2.5 overflow-y-auto pr-1">
            {workflowAudits.map((wa) => (
              <div key={wa.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <span className="font-semibold text-slate-900">{wa.workflow_name}</span>
                    <span className="ml-2 font-mono text-[11px] text-slate-500">{wa.filename}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-900">{wa.score}/100</span>
                    <StatusBadge status={wa.passed ? 'passed' : 'failed'} />
                  </div>
                </div>
                {wa.findings_json.length > 0 ? (
                  <ul className="mt-2 space-y-1 text-[11px] text-slate-700">
                    {wa.findings_json.map((f) => (
                      <li key={`${wa.id}-${f.rule_id}`} className="flex items-center gap-2">
                        <StatusBadge status={f.severity} />
                        <span className="font-mono font-semibold">{f.rule_id}</span>
                        <span>{f.title}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-[11px] text-emerald-700">
                    Zero security or reliability findings.
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
