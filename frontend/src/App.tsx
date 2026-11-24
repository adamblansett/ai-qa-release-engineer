import { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  Database,
  FlaskConical,
  GitBranch,
  LayoutDashboard,
  Rocket,
  ShieldCheck,
  Terminal,
} from 'lucide-react';
import {
  fetchApprovals,
  fetchAuditEvents,
  fetchCiRuns,
  fetchFlakyClusters,
  fetchHealth,
  fetchOverview,
  fetchRegressionBaselines,
  fetchRegressionRuns,
  fetchReleases,
  fetchTestSuites,
  fetchWorkflowAudits,
  seedDemoData,
  verifyAuditChain,
} from './api/client';
import { AuditLogView } from './components/AuditLogView';
import { CiTriageView } from './components/CiTriageView';
import { OverviewView } from './components/OverviewView';
import { RegressionView } from './components/RegressionView';
import { ReleaseGateView } from './components/ReleaseGateView';
import { TestGenView } from './components/TestGenView';
import type {
  ActorContext,
  ActorRole,
  ApprovalRequestItem,
  AuditChainVerify,
  AuditEventItem,
  CiBuildRunItem,
  FlakyClusterItem,
  HealthStatus,
  OverviewSummary,
  RegressionBaselineItem,
  RegressionRunItem,
  ReleaseCandidateItem,
  TestSuiteItem,
  WorkflowAuditItem,
} from './types/qa';

const NAV_TABS = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'testgen', label: 'E2E TestGen', icon: FlaskConical },
  { id: 'ci_triage', label: 'CI/CD Triage', icon: Terminal },
  { id: 'regression', label: 'Regression Gates', icon: GitBranch },
  { id: 'release_gate', label: 'Release Gate', icon: Rocket },
  { id: 'audit', label: 'Audit & Secrets', icon: ShieldCheck },
] as const;

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [offline, setOffline] = useState(false);
  const [activeTab, setActiveTab] = useState<string>('overview');
  const [actor, setActor] = useState<ActorContext>({
    email: 'release-manager@acme-qa.local',
    role: 'release_manager',
  });
  const [banner, setBanner] = useState<{ text: string; isError: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  const [overview, setOverview] = useState<OverviewSummary | null>(null);
  const [suites, setSuites] = useState<TestSuiteItem[]>([]);
  const [ciRuns, setCiRuns] = useState<CiBuildRunItem[]>([]);
  const [flakyClusters, setFlakyClusters] = useState<FlakyClusterItem[]>([]);
  const [workflowAudits, setWorkflowAudits] = useState<WorkflowAuditItem[]>([]);
  const [baselines, setBaselines] = useState<RegressionBaselineItem[]>([]);
  const [regressionRuns, setRegressionRuns] = useState<RegressionRunItem[]>([]);
  const [releases, setReleases] = useState<ReleaseCandidateItem[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequestItem[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEventItem[]>([]);
  const [chainStatus, setChainStatus] = useState<AuditChainVerify | null>(null);

  const notify = useCallback((text: string, isError = false) => {
    setBanner({ text, isError });
  }, []);

  const refreshWorkspace = useCallback(async () => {
    try {
      const [ov, st, cr, fc, wa, bl, rr, rel, apps, evs, chain] = await Promise.all([
        fetchOverview(actor),
        fetchTestSuites(actor),
        fetchCiRuns(actor),
        fetchFlakyClusters(actor),
        fetchWorkflowAudits(actor),
        fetchRegressionBaselines(actor),
        fetchRegressionRuns(actor),
        fetchReleases(actor),
        fetchApprovals(actor),
        fetchAuditEvents(actor),
        verifyAuditChain(actor),
      ]);
      setOverview(ov);
      setSuites(st);
      setCiRuns(cr);
      setFlakyClusters(fc);
      setWorkflowAudits(wa);
      setBaselines(bl);
      setRegressionRuns(rr);
      setReleases(rel);
      setApprovals(apps);
      setAuditEvents(evs);
      setChainStatus(chain);
    } catch {
      // Keep UI resilient if secondary APIs are unavailable during offline preview
    }
  }, [actor]);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const h = await fetchHealth();
        if (!cancelled) {
          setHealth(h);
          setOffline(false);
        }
        await refreshWorkspace();
      } catch {
        if (!cancelled) {
          setOffline(true);
        }
      }
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [refreshWorkspace]);

  async function handleLoadDemo(reset = false) {
    setBusy(true);
    try {
      const res = await seedDemoData(actor, reset);
      notify(res.message);
      await refreshWorkspace();
    } catch (err) {
      notify(err instanceof Error ? err.message : 'Demo seed failed', true);
    } finally {
      setBusy(false);
    }
  }

  function handleRoleChange(role: ActorRole) {
    const emailMap: Record<ActorRole, string> = {
      release_manager: 'release-manager@acme-qa.local',
      qa_engineer: 'qa.engineer@acme-qa.local',
      viewer: 'viewer@acme-qa.local',
      admin: 'admin@acme-qa.local',
    };
    const email = emailMap[role];
    setActor({ email, role });
    notify(`Switched active actor to ${email} (${role}).`);
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600">
              Phase 2 — Autonomous QA &amp; Release Governance
            </p>
            <h1 className="mt-0.5 text-xl font-bold tracking-tight text-slate-900">
              AI QA &amp; Release Engineer
            </h1>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <label className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700">
              <span>Role:</span>
              <select
                aria-label="Actor Role"
                value={actor.role}
                onChange={(e) => handleRoleChange(e.target.value as ActorRole)}
                className="bg-transparent font-semibold text-indigo-700 focus:outline-none"
              >
                <option value="release_manager">Release Manager</option>
                <option value="qa_engineer">QA Engineer</option>
                <option value="viewer">Viewer</option>
              </select>
            </label>

            <button
              type="button"
              onClick={() => handleLoadDemo(true)}
              disabled={busy || offline || actor.role === 'viewer'}
              className="inline-flex items-center gap-1.5 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
            >
              <Database className="h-3.5 w-3.5" />
              {busy ? 'Loading...' : 'Reset Demo Data'}
            </button>

            <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3.5 py-1.5 text-xs font-medium">
              <Activity
                className={`h-3.5 w-3.5 ${
                  health?.status === 'ok'
                    ? 'text-emerald-600'
                    : offline
                    ? 'text-amber-600'
                    : 'text-slate-400'
                }`}
              />
              <span>
                {health?.status === 'ok'
                  ? `API Healthy (${health.llm_provider})`
                  : offline
                  ? 'Offline Starter Preview'
                  : 'Checking API...'}
              </span>
            </div>
          </div>
        </div>

        <nav
          aria-label="QA & Release Modules"
          className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-6 pb-2"
        >
          {NAV_TABS.map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition ${
                  active
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {tab.label}
              </button>
            );
          })}
        </nav>
      </header>

      <main className="mx-auto max-w-6xl space-y-5 px-6 py-6">
        {banner && (
          <div
            role="status"
            className={`flex items-center justify-between rounded-xl border px-4 py-2.5 text-xs font-medium ${
              banner.isError
                ? 'border-rose-200 bg-rose-50 text-rose-800'
                : 'border-emerald-200 bg-emerald-50 text-emerald-800'
            }`}
          >
            <span>{banner.text}</span>
            <button
              type="button"
              onClick={() => setBanner(null)}
              className="ml-4 text-xs underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {activeTab === 'overview' && (
          <OverviewView
            actor={actor}
            overview={overview}
            approvals={approvals}
            onNavigate={setActiveTab}
            onLoadDemo={() => handleLoadDemo(false)}
            onRefresh={refreshWorkspace}
            onNotify={notify}
            busy={busy}
          />
        )}

        {activeTab === 'testgen' && (
          <TestGenView
            actor={actor}
            suites={suites}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}

        {activeTab === 'ci_triage' && (
          <CiTriageView
            actor={actor}
            runs={ciRuns}
            flakyClusters={flakyClusters}
            workflowAudits={workflowAudits}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}

        {activeTab === 'regression' && (
          <RegressionView
            actor={actor}
            baselines={baselines}
            runs={regressionRuns}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}

        {activeTab === 'release_gate' && (
          <ReleaseGateView
            actor={actor}
            releases={releases}
            regressionRuns={regressionRuns}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}

        {activeTab === 'audit' && (
          <AuditLogView
            actor={actor}
            approvals={approvals}
            events={auditEvents}
            chainStatus={chainStatus}
            onChainVerified={setChainStatus}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}
      </main>
    </div>
  );
}
