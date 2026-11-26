# AI QA & Release Engineer

> Open-source, self-hosted AI QA and release engineering platform for E2E test generation, CI/CD health checks, regression execution, and deployment verification.

**Roadmap Stage:** Phase 2 — Administrative, Quality & Specialized Additions · **Status:** Phase 2 Integrations & Production Hardening Implemented

## Core Capabilities

- **E2E Test Generation (`/api/v1/testgen`):** OpenAPI 3.x YAML/JSON and user-flow test synthesis producing runnable Playwright TypeScript and `pytest` + `httpx` suites with schema assertions, negative validation cases, auth guards, and HITL publish approvals.
- **CI/CD Health Checks & Semantic Triage (`/api/v1/ci-triage`):** Deterministic log parser & root-cause classifier (`infra_oom`, `timeout`, `dependency_error`, `lint_type_error`, `assertion_failure`), JUnit XML & Playwright JSON report ingestion, embedding-based semantic failure clustering, flaky-test transition clustering, and GitHub Actions YAML auditing (`WF001`–`WF008`).
- **Regression Execution (`/api/v1/regression`):** Contract compatibility diffing, recursive JSON snapshot diffs, deterministic LLM-eval rubric scoring with PII leak penalties, p95 latency drift checks, and HITL baseline promotion.
- **Deployment Verification (`/api/v1/release-gate`):** SSRF-guarded post-deploy smoke probes, OTel/Prometheus canary telemetry pull, 6-gate Go/No-Go readiness checklist, and HITL promotion & emergency rollback execution.
- **Webhooks, Worker Queue & Hardening (`/api/v1/integrations`, `/api/v1/jobs`, `/api/v1/auth`, `/api/v1/metrics`):** HMAC-SHA256 GitHub webhooks & PR check-run publisher, inline/Redis background job runner (`python -m app.jobs.worker`), scoped `X-API-Key` + Bearer JWT RBAC, sliding-window rate limiting, Prometheus metrics, SHA-256 audit chain, and outbound PII/CI-secret redaction.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for architecture and production deployment details.

## Architecture & Engineering Standards

- **Backend (`backend/`):** Python 3.12+, FastAPI, Pydantic v2, async SQLAlchemy 2.0 + Alembic migrations (`0001_initial_schema`), pure ASGI security-header middleware, and `/api/v1/health` (`/live`, `/ready`) probes.
- **Frontend (`frontend/`):** React 18, TypeScript, Vite, Tailwind CSS, and Vitest + Testing Library unit tests served behind unprivileged Nginx in production.
- **Privacy & AI Guardrails:** Offline deterministic `mock` mode for CI/dev, local-first open-weights Ollama support, and cloud PII/secret redaction enabled by default (`LLM_REDACT_PII_FOR_CLOUD=true`).
- **Containers & CI (`.github/workflows/ci.yml`):** Multi-stage Dockerfiles, PostgreSQL (`pgvector`) + Redis Compose topology, Ruff + Mypy + Pytest checks, TypeScript + Vitest + Vite build, `npm audit`, and Trivy filesystem scanning.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module and security architecture.

## Quickstart

### Backend (Local Dev & Tests)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Verify lint, types, and tests:

```bash
ruff check app tests
mypy app
pytest -v
```

### Frontend (Local Dev & Tests)

```bash
cd frontend
npm ci
npm run dev
```

Verify typecheck, unit tests, and production bundle:

```bash
npx tsc --noEmit
npm run test
npm run build
```

### Docker Compose

```bash
docker compose up --build
```

- Frontend UI: `http://localhost:3000`
- Backend API & OpenAPI Docs: `http://localhost:8000/docs`

---

## License

Licensed under the [MIT License](LICENSE).
