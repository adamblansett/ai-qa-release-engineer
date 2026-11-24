# AI QA & Release Engineer — Architecture Blueprint

## Overview

Open-source, self-hosted AI QA and release engineering platform for E2E test generation, CI/CD health checks, regression execution, and deployment verification.

This starter repository establishes the production baseline (typed configuration, security headers, health endpoints, CI checks, and Docker Compose topology) so domain features can be implemented cleanly without re-scaffolding infrastructure.

## Planned Domain Modules (`backend/app/`)

- `testgen/` — OpenAPI & DOM-flow test case synthesizer with schema assertions
- `ci_triage/` — Build log parser and root-cause classifier for failing jobs
- `regression/` — Deterministic test runner wrapper and baseline diff engine
- `release_gate/` — Canary health verification and go/no-go readiness checklist

## Security & Operational Invariants

1. **Fail-Fast Production Validation:** `validate_production_security()` refuses startup in `APP_ENV=production` if default dev secrets or wildcard CORS origins remain active.
2. **Cloud PII Redaction:** Outbound cloud LLM adapters run PII scrubbing when `LLM_REDACT_PII_FOR_CLOUD=true`.
3. **Human-in-the-Loop Approvals:** High-impact external writes (emails, accounting entries, identity changes, record merges) require explicit review states and immutable audit trails.
4. **Non-Root Containers:** Both the FastAPI API image and Nginx frontend image run as non-root users with `/api/v1/health/live` and `/api/v1/health/ready` probes.
