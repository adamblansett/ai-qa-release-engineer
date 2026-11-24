# AI QA & Release Engineer

> Open-source, self-hosted AI QA and release engineering platform for E2E test generation, CI/CD health checks, regression execution, and deployment verification.

**Roadmap Stage:** Phase 2 — Administrative, Quality & Specialized Additions · **Status:** Phase 1 Core Platform Implemented

## Core Capabilities

- **E2E Test Generation (`/api/v1/testgen`):** OpenAPI 3.x YAML/JSON and user-flow test synthesis producing runnable Playwright TypeScript and `pytest` + `httpx` suites with schema assertions, negative validation cases, auth guards, and HITL publish approvals.
- **CI/CD Health Checks (`/api/v1/ci-triage`):** Deterministic log parser & root-cause classifier (`infra_oom`, `timeout`, `dependency_error`, `lint_type_error`, `assertion_failure`), flaky-test transition clustering, and GitHub Actions YAML security/reliability auditing (`WF001`–`WF008`).
- **Regression Execution (`/api/v1/regression`):** Contract compatibility diffing, recursive JSON snapshot diffs, deterministic LLM-eval rubric scoring with PII leak penalties, p95 latency drift checks, and HITL baseline promotion.
- **Deployment Verification (`/api/v1/release-gate`):** SSRF-guarded post-deploy smoke probes, 6-gate Go/No-Go readiness checklist, canary SLO enforcement, and HITL promotion & emergency rollback execution.
- **Governance, RBAC & Guardrails (`/api/v1/audit`, `/api/v1/auth`):** Roles (`viewer`, `qa_engineer`, `release_manager`, `admin`), HMAC-SHA256 Bearer tokens, SHA-256 hash-chained audit trail with tamper verification, and outbound PII/CI-secret redaction before cloud inference.

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
