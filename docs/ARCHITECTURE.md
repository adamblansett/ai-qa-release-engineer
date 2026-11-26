# AI QA & Release Engineer — Architecture Blueprint

## Overview

Open-source, self-hosted AI QA and release engineering platform for E2E test generation, CI/CD health checks, regression execution, and deployment verification.

The Phase 1 implementation ships an end-to-end backend (`FastAPI` + async `SQLAlchemy` + `Alembic`), an LLM governance router with outbound PII & CI secret scrubbing, human-in-the-loop (HITL) approval gates, a SHA-256 hash-chained audit trail, and a React + Tailwind engineering console.

## Implemented Domain Modules (`backend/app/`)

1. **`testgen/`** — Spec-Driven E2E & Contract Test Synthesizer
   - Parses OpenAPI 3.x YAML/JSON specifications (resolving local `$ref` schemas) and structured browser user-flow steps.
   - Generates runnable Playwright TypeScript (`@playwright/test`) or `pytest` + `httpx` suites covering happy paths, schema/field-type assertions, validation edge cases (`400`/`422`), and auth guards (`401`/`403`).
   - Supports HITL `test_suite_publish` approval before marking generated suites approved.

2. **`ci_triage/`** — CI/CD Build Triage, Flaky Clustering & Workflow Validator
   - Extracts failure lines across pytest, Vitest/Jest, Playwright, and generic build runners and normalizes signatures (stripping timestamps, UUIDs, hex pointers, ports).
   - Classifies root causes (`infra_oom`, `timeout`, `auth_secret_error`, `dependency_error`, `lint_type_error`, `build_compile_error`, `assertion_failure`) with remediation guidance.
   - Clusters per-test execution history (`TestExecutionRecord`) to detect oscillating pass/fail tests and surface quarantine recommendations.
   - Validates GitHub Actions YAML workflows against rules `WF001`–`WF008` (permissions, write-all on PRs, timeouts, pinned actions, concurrency, script injection, `npm ci`, hardcoded secrets).

3. **`regression/`** — Contract, Snapshot & LLM-Eval Gate Engine
   - Evaluates breaking vs. additive API contract changes, recursive JSON snapshot diffs, deterministic LLM evaluation rubrics (keyword recall, token F1, JSON validity, forbidden/PII leakage), and p95 latency drift.
   - Supports HITL `baseline_promotion` approvals that atomically increment baseline versions and update snapshots/contracts.

4. **`release_gate/`** — Deployment Verification & Go/No-Go Readiness Gate
   - Runs SSRF-guarded post-deploy smoke probes (`simulated` or `live_http`, blocking metadata IPs `169.254.0.0/16` / `fe80::/10` / `metadata.google.internal` and non-HTTP schemes).
   - Computes a 6-point readiness checklist (`smoke_probes_green`, `canary_error_rate_ok`, `canary_latency_ok`, `regression_gate_passed`, `rollback_readiness_verified`, `no_blocking_ci_failures`).
   - Enforces HITL `release_promotion` and `rollback_execution` approvals via `release_manager` or `admin` roles.

5. **`audit/` & `llm/`** — Governance, RBAC & Outbound Secret Scrubbing
   - Role-based access control (`viewer`, `qa_engineer`, `release_manager`, `admin`) via HMAC-SHA256 Bearer JWT, scoped `X-API-Key` credentials (`api_keys`), or dev actor headers (`AUTH_REQUIRE_TOKEN=true` / `APP_ENV=production` enforces Bearer JWT or API key).
   - `redact_pii()` scrubs PEM private keys, credentialed DB URIs, JWTs, Bearer tokens, GitHub/AWS/Gemini/OpenAI keys, secret assignments, SSNs, emails, phones, and Luhn-valid card numbers before outbound cloud calls (`LLM_REDACT_PII_FOR_CLOUD=true`).
   - Every mutation appends to `audit_events` with a SHA-256 chain verifiable via `GET /api/v1/audit/events/verify`.

6. **`integrations/` & `jobs/`** — Live CI/CD Webhooks, Telemetry Pull & Worker Queue
   - `POST /api/v1/integrations/github/webhook` verifies `X-Hub-Signature-256` HMAC digests and auto-ingests `workflow_run` & `deployment_status` events; `POST /api/v1/integrations/github/publish-check` formats and posts PR Check Runs.
   - `POST /api/v1/ci-triage/ingest-report` parses XXE-safe JUnit XML and Playwright JSON reports; `embeddings.py` groups failures into semantic clusters.
   - `POST /api/v1/release-gate/releases/{id}/telemetry/pull` fetches SSRF-guarded Prometheus or OTel snapshot metrics.
   - `jobs/` executes `canary_smoke_sweep`, `embedding_reindex`, and `regression_suite_run` inline or via Redis `qa:jobs:queue` (`python -m app.jobs.worker`).
   - `RateLimitMiddleware` enforces sliding-window per-client limits (`429` + `Retry-After`) and `GET /api/v1/metrics` / `/metrics` emits Prometheus metrics alongside `X-Trace-Id` headers when `OTEL_ENABLED=true`.

## Security & Operational Invariants

1. **Fail-Fast Production Validation:** `validate_production_security()` refuses startup in `APP_ENV=production` if default dev secrets or wildcard CORS origins remain active.
2. **Cloud PII & Secret Redaction:** Outbound cloud LLM adapters scrub PII and CI credentials when `LLM_REDACT_PII_FOR_CLOUD=true`.
3. **Human-in-the-Loop Approvals:** Promotions, rollbacks, baseline updates, and suite publications require explicit `release_manager`/`admin` decisions logged in an immutable SHA-256 audit chain.
4. **Non-Root Containers:** Both the FastAPI API image and Nginx frontend image run as non-root users with `/api/v1/health/live` and `/api/v1/health/ready` probes.
