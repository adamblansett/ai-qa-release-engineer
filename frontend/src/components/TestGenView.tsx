import { useState } from 'react';
import { Check, Copy, FileCode2, Play, ShieldAlert } from 'lucide-react';
import {
  requestSuiteApproval,
  synthesizeFlowSuite,
  synthesizeOpenApiSuite,
} from '../api/client';
import type { ActorContext, FlowStepInput, TestSuiteItem } from '../types/qa';
import { StatusBadge } from './StatusBadge';

interface TestGenViewProps {
  actor: ActorContext;
  suites: TestSuiteItem[];
  onRefresh: () => Promise<void>;
  onNotify: (text: string, isError?: boolean) => void;
}

const DEFAULT_OPENAPI_SPEC = `openapi: 3.0.3
info:
  title: Release Health API
  version: 1.0.0
paths:
  /api/v1/deployments:
    post:
      operationId: registerDeployment
      security:
        - bearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [version_tag, environment]
              properties:
                version_tag:
                  type: string
                environment:
                  type: string
      responses:
        "201":
          description: Created
          content:
            application/json:
              schema:
                type: object
                required: [id, status]
                properties:
                  id:
                    type: string
                  status:
                    type: string`;

export function TestGenView({ actor, suites, onRefresh, onNotify }: TestGenViewProps) {
  const [mode, setMode] = useState<'openapi' | 'flow'>('openapi');
  const [suiteName, setSuiteName] = useState('Deployments Contract Suite');
  const [framework, setFramework] = useState<'playwright' | 'pytest'>('playwright');
  const [baseUrl, setBaseUrl] = useState('http://localhost:8000');
  const [specText, setSpecText] = useState(DEFAULT_OPENAPI_SPEC);
  const [flowName, setFlowName] = useState('Login and Verify Dashboard');
  const [stepsJson, setStepsJson] = useState(
    JSON.stringify(
      [
        { action: 'navigate', target: '/', value: '', expected: '' },
        { action: 'assert_visible', target: 'h1', value: '', expected: '' },
        { action: 'api_check', target: '/api/v1/health', value: '', expected: '' },
      ] satisfies FlowStepInput[],
      null,
      2,
    ),
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const canMutate = actor.role !== 'viewer';
  const activeSuite = suites.find((s) => s.id === selectedId) || suites[0] || null;

  async function handleSynthesize(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      let created: TestSuiteItem;
      if (mode === 'openapi') {
        created = await synthesizeOpenApiSuite(actor, {
          suite_name: suiteName,
          spec_text: specText,
          framework,
          target_base_url: baseUrl,
          include_negative_cases: true,
          include_auth_cases: true,
        });
      } else {
        const parsedSteps = JSON.parse(stepsJson) as FlowStepInput[];
        created = await synthesizeFlowSuite(actor, {
          suite_name: suiteName,
          flow_name: flowName,
          target_base_url: baseUrl,
          steps: parsedSteps,
        });
      }
      setSelectedId(created.id);
      onNotify(`Synthesized suite '${created.name}' with ${created.case_count} test cases.`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Test synthesis failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleRequestApproval(suiteId: string) {
    setBusy(true);
    try {
      await requestSuiteApproval(actor, suiteId);
      onNotify('Submitted suite publication for Release Manager approval.');
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Approval request failed', true);
    } finally {
      setBusy(false);
    }
  }

  async function handleCopyCode(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      onNotify('Clipboard copy unavailable in this browser context.', true);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm lg:col-span-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">Spec-Driven Test Synthesizer</h2>
          <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-xs">
            <button
              type="button"
              onClick={() => setMode('openapi')}
              className={`rounded-md px-2.5 py-1 font-medium ${
                mode === 'openapi' ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-600'
              }`}
            >
              OpenAPI
            </button>
            <button
              type="button"
              onClick={() => setMode('flow')}
              className={`rounded-md px-2.5 py-1 font-medium ${
                mode === 'flow' ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-600'
              }`}
            >
              User Flow
            </button>
          </div>
        </div>

        <form onSubmit={handleSynthesize} className="mt-4 space-y-3">
          <div>
            <label className="block text-xs font-medium text-slate-700">Suite Name</label>
            <input
              type="text"
              value={suiteName}
              onChange={(e) => setSuiteName(e.target.value)}
              required
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs focus:border-indigo-400 focus:outline-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-700">Target Base URL</label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                required
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs focus:border-indigo-400 focus:outline-none"
              />
            </div>
            {mode === 'openapi' ? (
              <div>
                <label className="block text-xs font-medium text-slate-700">Framework</label>
                <select
                  value={framework}
                  onChange={(e) => setFramework(e.target.value as 'playwright' | 'pytest')}
                  className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs focus:border-indigo-400 focus:outline-none"
                >
                  <option value="playwright">Playwright (TS)</option>
                  <option value="pytest">Pytest + httpx</option>
                </select>
              </div>
            ) : (
              <div>
                <label className="block text-xs font-medium text-slate-700">Flow Name</label>
                <input
                  type="text"
                  value={flowName}
                  onChange={(e) => setFlowName(e.target.value)}
                  required
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs focus:border-indigo-400 focus:outline-none"
                />
              </div>
            )}
          </div>

          {mode === 'openapi' ? (
            <div>
              <label className="block text-xs font-medium text-slate-700">
                OpenAPI 3.x Spec (JSON or YAML)
              </label>
              <textarea
                rows={11}
                value={specText}
                onChange={(e) => setSpecText(e.target.value)}
                required
                className="mt-1 w-full rounded-lg border border-slate-200 font-mono text-[11px] leading-relaxed focus:border-indigo-400 focus:outline-none p-2.5"
              />
            </div>
          ) : (
            <div>
              <label className="block text-xs font-medium text-slate-700">
                User Flow Steps (JSON Array)
              </label>
              <textarea
                rows={11}
                value={stepsJson}
                onChange={(e) => setStepsJson(e.target.value)}
                required
                className="mt-1 w-full rounded-lg border border-slate-200 font-mono text-[11px] leading-relaxed focus:border-indigo-400 focus:outline-none p-2.5"
              />
            </div>
          )}

          <button
            type="submit"
            disabled={busy || !canMutate}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            <Play className="h-3.5 w-3.5" />
            {busy ? 'Synthesizing...' : 'Synthesize Test Suite'}
          </button>
          {!canMutate && (
            <p className="text-[11px] text-amber-700">
              Viewer role is read-only. Switch to QA Engineer or Release Manager to synthesize.
            </p>
          )}
        </form>
      </section>

      <section className="space-y-4 lg:col-span-3">
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-900">
            Synthesized Suites ({suites.length})
          </h2>
          {suites.length === 0 ? (
            <p className="mt-3 text-xs text-slate-500">No synthesized test suites yet.</p>
          ) : (
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {suites.map((suite) => (
                <button
                  key={suite.id}
                  type="button"
                  onClick={() => setSelectedId(suite.id)}
                  className={`rounded-lg border p-3 text-left transition ${
                    activeSuite?.id === suite.id
                      ? 'border-indigo-500 bg-indigo-50/50'
                      : 'border-slate-200 hover:border-slate-300'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs font-semibold text-slate-900">
                      {suite.name}
                    </span>
                    <StatusBadge status={suite.status} />
                  </div>
                  <p className="mt-1 text-[11px] text-slate-500">
                    {suite.framework} · {suite.source_type} · {suite.case_count} cases
                  </p>
                </button>
              ))}
            </div>
          )}
        </div>

        {activeSuite && (
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <FileCode2 className="h-4 w-4 text-indigo-600" />
                  <h3 className="text-sm font-semibold text-slate-900">{activeSuite.name}</h3>
                  <StatusBadge status={activeSuite.status} />
                </div>
                <p className="mt-1 text-xs text-slate-600">{activeSuite.ai_summary}</p>
              </div>
              <div className="flex items-center gap-2">
                {activeSuite.status === 'draft' && canMutate && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => handleRequestApproval(activeSuite.id)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-800 hover:bg-amber-100"
                  >
                    <ShieldAlert className="h-3.5 w-3.5" />
                    Request Publish Approval
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => handleCopyCode(activeSuite.generated_code)}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                  {copied ? 'Copied' : 'Copy Code'}
                </button>
              </div>
            </div>

            <div className="space-y-2">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Generated Cases &amp; Schema Assertions ({activeSuite.cases.length})
              </h4>
              <div className="max-h-48 space-y-2 overflow-y-auto pr-1">
                {activeSuite.cases.map((tc) => (
                  <div
                    key={tc.id}
                    className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-semibold text-slate-900">{tc.title}</span>
                      <div className="flex items-center gap-1.5">
                        <span className="rounded bg-slate-200 px-1.5 py-0.5 font-mono text-[10px] font-semibold">
                          {tc.http_method}
                        </span>
                        <StatusBadge status={tc.category} />
                      </div>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-600">
                      Assertions: {tc.assertions_json.join(' · ')}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Runnable Test Output
              </h4>
              <pre className="mt-1.5 max-h-64 overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] leading-relaxed text-slate-100">
                {activeSuite.generated_code}
              </pre>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
