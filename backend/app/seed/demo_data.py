from datetime import timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import create_approval_request, record_audit_event
from app.ci_triage.analyzer import classify_root_cause, normalize_signature, parse_ci_log
from app.ci_triage.workflow_validator import validate_workflow_yaml
from app.core.auth import Actor
from app.core.config import Settings
from app.db.base import utcnow
from app.db.models import (
    ApprovalRequest,
    AuditEvent,
    CiBuildRun,
    GeneratedTestCase,
    RegressionBaseline,
    RegressionRun,
    ReleaseCandidate,
    SmokeProbeResult,
    TestExecutionRecord,
    TestSuite,
    WorkflowAudit,
)
from app.llm.router import LLMRouter
from app.regression.engine import evaluate_regression_run
from app.release_gate.evaluator import evaluate_release_checklist
from app.testgen.schemas import FlowStep
from app.testgen.synthesizer import synthesize_from_openapi, synthesize_from_user_flow


class SeedResponse(BaseModel):
    seeded: bool
    message: str
    test_suites: int
    ci_runs: int
    regression_runs: int
    release_candidates: int
    pending_approvals: int


_DEMO_OPENAPI_YAML = """openapi: 3.0.3
info:
  title: Checkout & Payments Service
  version: 2.14.0
paths:
  /api/v1/orders:
    post:
      operationId: createOrder
      security:
        - bearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [customer_email, amount_cents]
              properties:
                customer_email:
                  type: string
                  format: email
                amount_cents:
                  type: integer
      responses:
        "201":
          description: Created
          content:
            application/json:
              schema:
                type: object
                required: [order_id, status]
                properties:
                  order_id:
                    type: string
                  status:
                    type: string
  /api/v1/health:
    get:
      operationId: serviceHealth
      responses:
        "200":
          description: Healthy
          content:
            application/json:
              schema:
                type: object
                required: [status]
                properties:
                  status:
                    type: string
"""

_HARDENED_WORKFLOW_YAML = """name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
permissions:
  contents: read
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - run: npm ci && npm test
"""

_INSECURE_WORKFLOW_YAML = """name: PR Preview
on:
  pull_request:
    branches: [main]
permissions: write-all
jobs:
  preview:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@main
      - run: echo "Title ${{ github.event.pull_request.title }}" && npm install
"""


async def _clear_all_tables(db: AsyncSession) -> None:
    for model in (
        SmokeProbeResult,
        ReleaseCandidate,
        RegressionRun,
        RegressionBaseline,
        WorkflowAudit,
        TestExecutionRecord,
        CiBuildRun,
        GeneratedTestCase,
        TestSuite,
        ApprovalRequest,
        AuditEvent,
    ):
        await db.execute(delete(model))
    await db.flush()


async def seed_demo_dataset(
    db: AsyncSession,
    *,
    llm_router: LLMRouter,
    settings: Settings,
    actor: Actor,
    reset: bool = False,
) -> SeedResponse:
    """Populate realistic idempotent demo data across all four QA & Release modules."""
    existing_suites = int(
        (await db.execute(select(func.count()).select_from(TestSuite))).scalar_one()
    )
    if existing_suites > 0 and not reset:
        ci_cnt = int((await db.execute(select(func.count()).select_from(CiBuildRun))).scalar_one())
        reg_cnt = int(
            (await db.execute(select(func.count()).select_from(RegressionRun))).scalar_one()
        )
        rel_cnt = int(
            (await db.execute(select(func.count()).select_from(ReleaseCandidate))).scalar_one()
        )
        app_cnt = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(ApprovalRequest)
                    .where(ApprovalRequest.status == "pending")
                )
            ).scalar_one()
        )
        return SeedResponse(
            seeded=False,
            message="Demo QA & Release dataset already initialized.",
            test_suites=existing_suites,
            ci_runs=ci_cnt,
            regression_runs=reg_cnt,
            release_candidates=rel_cnt,
            pending_approvals=app_cnt,
        )

    if reset:
        await _clear_all_tables(db)

    base_time = utcnow() - timedelta(hours=6)

    # 1. TestGen Suites
    oa_cases, oa_code, oa_hash = synthesize_from_openapi(
        suite_name="Checkout & Payments API Suite",
        spec_text=_DEMO_OPENAPI_YAML,
        framework="playwright",
        target_base_url="https://staging-checkout.internal",
        include_negative_cases=True,
        include_auth_cases=True,
    )
    oa_summary = await llm_router.generate(
        prompt="Checkout & Payments API Suite synthesized with 4 contract & auth cases.",
        task_type="testgen_synthesis",
    )
    suite_api = TestSuite(
        name="Checkout & Payments API Suite",
        source_type="openapi",
        framework="playwright",
        target_base_url="https://staging-checkout.internal",
        source_spec_raw=_DEMO_OPENAPI_YAML,
        spec_hash=oa_hash,
        case_count=len(oa_cases),
        status="approved",
        generated_code=oa_code,
        ai_summary=oa_summary.content,
        created_by=actor.email,
        created_at=base_time,
    )
    db.add(suite_api)
    await db.flush()
    for idx, c in enumerate(oa_cases):
        db.add(
            GeneratedTestCase(
                suite_id=suite_api.id,
                case_key=c.case_key,
                title=c.title,
                category=c.category,
                http_method=c.http_method,
                endpoint_or_route=c.endpoint_or_route,
                assertions_json=c.assertions,
                code_snippet=c.code_snippet,
                priority=c.priority,
                created_at=base_time + timedelta(seconds=idx),
            )
        )

    flow_steps = [
        FlowStep(action="navigate", target="/checkout"),
        FlowStep(action="fill", target="[data-testid='email']", value="qa.buyer@example.com"),
        FlowStep(action="click", target="button[type='submit']"),
        FlowStep(action="assert_visible", target="[data-testid='order-confirmed']"),
        FlowStep(action="api_check", target="/api/v1/health"),
    ]
    flow_cases, flow_code, flow_hash = synthesize_from_user_flow(
        suite_name="Checkout Cart E2E Flow",
        flow_name="Customer Card Checkout",
        target_base_url="https://staging-web.internal",
        steps=flow_steps,
    )
    suite_flow = TestSuite(
        name="Checkout Cart E2E Flow",
        source_type="user_flow",
        framework="playwright",
        target_base_url="https://staging-web.internal",
        source_spec_raw="[]",
        spec_hash=flow_hash,
        case_count=len(flow_cases),
        status="pending_approval",
        generated_code=flow_code,
        ai_summary="Playwright E2E checkout journey & 503 resilience test pending QA review.",
        created_by="qa.engineer@acme-qa.local",
        created_at=base_time + timedelta(minutes=15),
    )
    db.add(suite_flow)
    await db.flush()
    for idx, c in enumerate(flow_cases):
        db.add(
            GeneratedTestCase(
                suite_id=suite_flow.id,
                case_key=c.case_key,
                title=c.title,
                category=c.category,
                http_method=c.http_method,
                endpoint_or_route=c.endpoint_or_route,
                assertions_json=c.assertions,
                code_snippet=c.code_snippet,
                priority=c.priority,
                created_at=base_time + timedelta(minutes=15, seconds=idx),
            )
        )
    suite_approval = await create_approval_request(
        db,
        entity_type="test_suite_publish",
        entity_id=suite_flow.id,
        action_requested="Publish playwright suite 'Checkout Cart E2E Flow' (2 cases)",
        summary="Publish synthesized user flow E2E suite to nightly regression runner.",
        risk_level="low",
        requested_by="qa.engineer@acme-qa.local",
    )
    suite_flow.approval_id = suite_approval.id

    # 2. CI/CD Build Runs & Flaky History
    ci_specs: list[dict[str, Any]] = [
        {
            "pipeline": "checkout-ci",
            "branch": "main",
            "sha": "sha-v2140",
            "job": "backend-pytest",
            "status": "passed",
            "dur": 94.2,
            "log": "24 passed in 9.1s",
            "outcomes": [
                ("tests/test_checkout.py::test_checkout_discount_race", "passed", ""),
                ("tests/test_orders.py::test_create_order_idempotent", "passed", ""),
            ],
        },
        {
            "pipeline": "checkout-ci",
            "branch": "feat/promo-stack",
            "sha": "sha-promo1",
            "job": "backend-pytest",
            "status": "failed",
            "dur": 112.5,
            "log": (
                "FAILED tests/test_checkout.py::test_checkout_discount_race - "
                "TimeoutError: waiting for redis lock timed out after 5000ms"
            ),
            "outcomes": [
                (
                    "tests/test_checkout.py::test_checkout_discount_race",
                    "failed",
                    "TimeoutError: waiting for redis lock timed out",
                ),
                ("tests/test_orders.py::test_create_order_idempotent", "passed", ""),
            ],
        },
        {
            "pipeline": "checkout-ci",
            "branch": "main",
            "sha": "sha-main-2",
            "job": "backend-pytest",
            "status": "passed",
            "dur": 88.0,
            "log": "24 passed in 8.4s",
            "outcomes": [
                ("tests/test_checkout.py::test_checkout_discount_race", "passed", ""),
                ("tests/test_orders.py::test_create_order_idempotent", "passed", ""),
            ],
        },
        {
            "pipeline": "checkout-ci",
            "branch": "feat/receipt-v2",
            "sha": "sha-991ab2",
            "job": "backend-pytest",
            "status": "failed",
            "dur": 120.4,
            "log": (
                "FAILED tests/test_checkout.py::test_checkout_discount_race - "
                "TimeoutError: waiting for redis lock timed out after 5000ms"
            ),
            "outcomes": [
                (
                    "tests/test_checkout.py::test_checkout_discount_race",
                    "failed",
                    "TimeoutError: waiting for redis lock timed out",
                ),
                ("tests/test_orders.py::test_create_order_idempotent", "passed", ""),
            ],
        },
        {
            "pipeline": "checkout-ci",
            "branch": "feat/cache-warmup",
            "sha": "sha-oom77",
            "job": "frontend-vitest",
            "status": "failed",
            "dur": 205.0,
            "log": (
                "FATAL ERROR: Reached heap limit Allocation failed - "
                "JavaScript heap out of memory"
            ),
            "outcomes": [
                ("src/test/Cart.test.tsx", "passed", ""),
            ],
        },
        {
            "pipeline": "checkout-ci",
            "branch": "release/v2.15.0-rc1",
            "sha": "sha-v2150rc1",
            "job": "e2e-playwright",
            "status": "failed",
            "dur": 176.8,
            "log": (
                "1) [chromium] › checkout.spec.ts:44 › payment redirect\n"
                "AssertionError: expected status 200 but received 502 Bad Gateway"
            ),
            "outcomes": [
                (
                    "checkout.spec.ts › payment redirect",
                    "failed",
                    "AssertionError: expected status 200 but received 502 Bad Gateway",
                ),
                ("tests/test_checkout.py::test_checkout_discount_race", "passed", ""),
            ],
        },
    ]

    for idx, spec in enumerate(ci_specs):
        extracted, _ = parse_ci_log(spec["log"])
        r_status, cat, sig, conf, rem = classify_root_cause(
            raw_log=spec["log"],
            status_hint=spec["status"],
            extracted_errors=extracted,
        )
        run_obj = CiBuildRun(
            pipeline_name=spec["pipeline"],
            branch=spec["branch"],
            commit_sha=spec["sha"],
            job_name=spec["job"],
            status=r_status,
            duration_seconds=spec["dur"],
            raw_log=spec["log"],
            root_cause_category=cat,
            failure_signature=sig,
            confidence=conf,
            remediation_summary=rem,
            ai_explanation=f"Deterministic triage: classified as {cat} ({sig[:120]}).",
            extracted_errors_json=extracted,
            created_at=base_time + timedelta(minutes=30 + idx * 10),
        )
        db.add(run_obj)
        await db.flush()
        for t_idx, (t_name, t_outcome, t_msg) in enumerate(spec["outcomes"]):
            db.add(
                TestExecutionRecord(
                    build_run_id=run_obj.id,
                    test_name=t_name,
                    suite_name="checkout-core",
                    outcome=t_outcome,
                    duration_ms=210.0 + t_idx * 45.0,
                    error_signature=normalize_signature(t_msg) if t_msg else "",
                    error_message=t_msg,
                    created_at=base_time + timedelta(minutes=30 + idx * 10, seconds=t_idx + 1),
                )
            )

    for wf_name, fname, wf_yaml in (
        ("Hardened Production CI", ".github/workflows/ci.yml", _HARDENED_WORKFLOW_YAML),
        ("PR Preview Unhardened", ".github/workflows/pr-preview.yml", _INSECURE_WORKFLOW_YAML),
    ):
        wf_passed, wf_score, wf_findings = validate_workflow_yaml(wf_yaml)
        db.add(
            WorkflowAudit(
                workflow_name=wf_name,
                filename=fname,
                workflow_yaml=wf_yaml,
                passed=wf_passed,
                score=wf_score,
                findings_json=wf_findings,
                created_at=base_time + timedelta(hours=2),
            )
        )

    # 3. Regression Baselines & Runs
    checkout_baseline_payload: dict[str, Any] = {
        "latency_p95_ms": 145.0,
        "contracts": {
            "POST /api/v1/orders": {
                "status": 201,
                "required_fields": ["order_id", "status"],
                "field_types": {"order_id": "string", "status": "string"},
            },
            "GET /api/v1/health": {
                "status": 200,
                "required_fields": ["status"],
                "field_types": {"status": "string"},
            },
        },
        "snapshots": {
            "checkout_receipt": {
                "currency": "USD",
                "tax_engine": "v2",
                "requires_3ds": True,
            }
        },
    }
    baseline_checkout = RegressionBaseline(
        suite_name="checkout-api",
        service_name="checkout-service",
        gate_type="combined",
        version=3,
        baseline_payload_json=checkout_baseline_payload,
        updated_by=actor.email,
        updated_at=base_time + timedelta(hours=2, minutes=15),
    )
    db.add(baseline_checkout)

    llm_baseline_payload: dict[str, Any] = {
        "latency_p95_ms": 320.0,
        "llm_evals": [
            {
                "id": "triage_oom",
                "prompt": "Classify exit code 137 failure.",
                "reference_answer": "Increase runner memory limits to fix OOM exit code 137.",
                "required_keywords": ["memory", "137"],
                "forbidden_terms": ["ignore failure"],
                "require_json": False,
                "baseline_score": 0.9,
            }
        ],
    }
    baseline_llm = RegressionBaseline(
        suite_name="support-triage-agent",
        service_name="ci-triage-worker",
        gate_type="llm_eval",
        version=1,
        baseline_payload_json=llm_baseline_payload,
        updated_by=actor.email,
        updated_at=base_time + timedelta(hours=2, minutes=20),
    )
    db.add(baseline_llm)
    await db.flush()

    ev_pass = evaluate_regression_run(
        baseline_payload=checkout_baseline_payload,
        candidate_payload=checkout_baseline_payload,
        candidate_latency_p95_ms=148.0,
        settings=settings,
    )
    reg_run_pass = RegressionRun(
        baseline_id=baseline_checkout.id,
        suite_name="checkout-api",
        commit_sha="sha-v2140",
        branch="main",
        gate_type="combined",
        status=str(ev_pass["status"]),
        total_checks=int(ev_pass["total_checks"]),
        passed_checks=int(ev_pass["passed_checks"]),
        failed_checks=int(ev_pass["failed_checks"]),
        latency_p95_ms=148.0,
        latency_drift_pct=float(ev_pass["latency_drift_pct"]),
        llm_eval_score=ev_pass["llm_eval_score"],
        candidate_payload_json=checkout_baseline_payload,
        diff_report_json=dict(ev_pass["diff_report"]),
        ai_summary="All contract schemas and snapshots matched baseline v3 (+2.07% latency drift).",
        executed_by="ci-runner@acme-qa.local",
        created_at=base_time + timedelta(hours=3),
    )
    db.add(reg_run_pass)

    cand_diff_payload: dict[str, Any] = {
        "contracts": {
            "POST /api/v1/orders": {
                "status": 201,
                "required_fields": ["order_id", "status"],
                "field_types": {
                    "order_id": "string",
                    "status": "string",
                    "receipt_url": "string",
                },
            },
            "GET /api/v1/health": {
                "status": 200,
                "required_fields": ["status"],
                "field_types": {"status": "string"},
            },
        },
        "snapshots": {
            "checkout_receipt": {
                "currency": "USD",
                "tax_engine": "v3",
                "requires_3ds": True,
            }
        },
    }
    ev_diff = evaluate_regression_run(
        baseline_payload=checkout_baseline_payload,
        candidate_payload=cand_diff_payload,
        candidate_latency_p95_ms=152.0,
        settings=settings,
    )
    reg_run_diff = RegressionRun(
        baseline_id=baseline_checkout.id,
        suite_name="checkout-api",
        commit_sha="sha-991ab2",
        branch="feat/receipt-v2",
        gate_type="combined",
        status=str(ev_diff["status"]),
        total_checks=int(ev_diff["total_checks"]),
        passed_checks=int(ev_diff["passed_checks"]),
        failed_checks=int(ev_diff["failed_checks"]),
        latency_p95_ms=152.0,
        latency_drift_pct=float(ev_diff["latency_drift_pct"]),
        llm_eval_score=ev_diff["llm_eval_score"],
        candidate_payload_json=cand_diff_payload,
        diff_report_json=dict(ev_diff["diff_report"]),
        ai_summary="Snapshot diff detected at $.tax_engine (v2 -> v3); review for promotion.",
        executed_by="qa.engineer@acme-qa.local",
        created_at=base_time + timedelta(hours=3, minutes=20),
    )
    db.add(reg_run_diff)
    await db.flush()

    baseline_approval = await create_approval_request(
        db,
        entity_type="baseline_promotion",
        entity_id=reg_run_diff.id,
        action_requested="Promote regression baseline for 'checkout-api' (sha-991ab2)",
        summary="Promote tax_engine v3 snapshot & additive receipt_url contract field.",
        risk_level="medium",
        requested_by="qa.engineer@acme-qa.local",
    )
    reg_run_diff.promotion_approval_id = baseline_approval.id

    llm_cand = {
        "llm_eval_outputs": {
            "triage_oom": "Increase runner memory limits to fix OOM exit code 137."
        }
    }
    ev_llm = evaluate_regression_run(
        baseline_payload=llm_baseline_payload,
        candidate_payload=llm_cand,
        candidate_latency_p95_ms=315.0,
        settings=settings,
    )
    db.add(
        RegressionRun(
            baseline_id=baseline_llm.id,
            suite_name="support-triage-agent",
            commit_sha="sha-v2140",
            branch="main",
            gate_type="llm_eval",
            status=str(ev_llm["status"]),
            total_checks=int(ev_llm["total_checks"]),
            passed_checks=int(ev_llm["passed_checks"]),
            failed_checks=int(ev_llm["failed_checks"]),
            latency_p95_ms=315.0,
            latency_drift_pct=float(ev_llm["latency_drift_pct"]),
            llm_eval_score=ev_llm["llm_eval_score"],
            candidate_payload_json=llm_cand,
            diff_report_json=dict(ev_llm["diff_report"]),
            ai_summary="LLM-eval rubric passed with 1.0 score and zero PII leakage.",
            executed_by="ci-runner@acme-qa.local",
            created_at=base_time + timedelta(hours=3, minutes=30),
        )
    )

    # 4. Release Candidates & Smoke Probes
    rel_go = ReleaseCandidate(
        version_tag="v2.14.0",
        service_name="checkout-service",
        environment="production",
        commit_sha="sha-v2140",
        previous_version_tag="v2.13.4",
        rollback_runbook_url="https://runbooks.internal/checkout/rollback-v214",
        rollback_verified=True,
        canary_error_rate_pct=0.12,
        canary_p95_latency_ms=148.0,
        canary_traffic_pct=25,
        regression_run_id=reg_run_pass.id,
        created_by=actor.email,
        created_at=base_time + timedelta(hours=4),
    )
    db.add(rel_go)
    await db.flush()

    go_probes = [
        SmokeProbeResult(
            release_id=rel_go.id,
            probe_name="checkout-health-ready",
            target_url="https://canary.checkout.internal/api/v1/health/ready",
            http_method="GET",
            expected_status=200,
            actual_status=200,
            latency_ms=38.4,
            max_latency_ms=250.0,
            expected_body_contains="ok",
            passed=True,
            mode="simulated",
            error_detail="",
            executed_at=base_time + timedelta(hours=4, minutes=2),
        ),
        SmokeProbeResult(
            release_id=rel_go.id,
            probe_name="orders-contract-probe",
            target_url="https://canary.checkout.internal/api/v1/orders/smoke",
            http_method="GET",
            expected_status=200,
            actual_status=200,
            latency_ms=72.1,
            max_latency_ms=300.0,
            expected_body_contains="order_id",
            passed=True,
            mode="simulated",
            error_detail="",
            executed_at=base_time + timedelta(hours=4, minutes=3),
        ),
    ]
    for p in go_probes:
        db.add(p)

    go_score, go_decision, go_checklist = evaluate_release_checklist(
        release=rel_go,
        probes=go_probes,
        regression_run=reg_run_pass,
        blocking_ci_runs=[],
        settings=settings,
    )
    rel_go.readiness_score = go_score
    rel_go.decision = go_decision
    rel_go.checklist_json = go_checklist
    rel_go.ai_readiness_brief = (
        "All 6 release verification gates passed (100/100 GO). Ready for Release Manager sign-off."
    )
    rel_go.status = "pending_approval"
    promo_approval = await create_approval_request(
        db,
        entity_type="release_promotion",
        entity_id=rel_go.id,
        action_requested="Promote checkout-service v2.14.0 to production",
        summary="Readiness 100/100 (GO). Canary error 0.12%, p95 148ms, rollback v2.13.4 verified.",
        risk_level="low",
        requested_by="qa.engineer@acme-qa.local",
    )
    rel_go.approval_id = promo_approval.id

    rel_nogo = ReleaseCandidate(
        version_tag="v2.15.0-rc1",
        service_name="checkout-service",
        environment="staging-canary",
        commit_sha="sha-v2150rc1",
        previous_version_tag="v2.14.0",
        rollback_runbook_url="https://runbooks.internal/checkout/rollback-v215",
        rollback_verified=True,
        canary_error_rate_pct=2.45,
        canary_p95_latency_ms=640.0,
        canary_traffic_pct=5,
        regression_run_id=reg_run_diff.id,
        created_by=actor.email,
        created_at=base_time + timedelta(hours=4, minutes=30),
    )
    db.add(rel_nogo)
    await db.flush()

    nogo_probes = [
        SmokeProbeResult(
            release_id=rel_nogo.id,
            probe_name="payment-redirect-smoke",
            target_url="https://canary-rc1.checkout.internal/api/v1/payments/callback",
            http_method="GET",
            expected_status=200,
            actual_status=502,
            latency_ms=612.0,
            max_latency_ms=400.0,
            expected_body_contains="ok",
            passed=False,
            mode="simulated",
            error_detail="Expected status 200, got 502. Latency 612.0ms exceeded max 400.0ms.",
            executed_at=base_time + timedelta(hours=4, minutes=32),
        )
    ]
    for p in nogo_probes:
        db.add(p)

    blocking_ci = list(
        (
            await db.execute(
                select(CiBuildRun).where(
                    CiBuildRun.commit_sha == "sha-v2150rc1",
                    CiBuildRun.status == "failed",
                )
            )
        )
        .scalars()
        .all()
    )
    nogo_score, nogo_decision, nogo_checklist = evaluate_release_checklist(
        release=rel_nogo,
        probes=nogo_probes,
        regression_run=reg_run_diff,
        blocking_ci_runs=blocking_ci,
        settings=settings,
    )
    rel_nogo.readiness_score = nogo_score
    rel_nogo.decision = nogo_decision
    rel_nogo.checklist_json = nogo_checklist
    rel_nogo.ai_readiness_brief = (
        "Release NO-GO: Canary error rate (2.45%) and smoke probe 502 breach SLOs; rollback queued."
    )
    rel_nogo.status = "blocked"
    rb_approval = await create_approval_request(
        db,
        entity_type="rollback_execution",
        entity_id=rel_nogo.id,
        action_requested="Rollback checkout-service v2.15.0-rc1 -> v2.14.0",
        summary="Canary 502 probe failure and 2.45% error rate; execute rollback to v2.14.0.",
        risk_level="high",
        requested_by="qa.engineer@acme-qa.local",
    )
    rel_nogo.rollback_approval_id = rb_approval.id

    await record_audit_event(
        db,
        event_type="seed.initialized",
        actor=actor,
        entity_type="workspace",
        entity_id="demo-dataset",
        action="seed_demo_data",
        details={
            "test_suites": 2,
            "ci_runs": len(ci_specs),
            "regression_runs": 3,
            "release_candidates": 2,
            "pending_approvals": 4,
        },
    )
    await db.commit()

    return SeedResponse(
        seeded=True,
        message="Seeded realistic QA & Release Engineering demo dataset across all modules.",
        test_suites=2,
        ci_runs=len(ci_specs),
        regression_runs=3,
        release_candidates=2,
        pending_approvals=4,
    )
