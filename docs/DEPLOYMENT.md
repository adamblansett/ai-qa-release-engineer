# Deployment & Production Hardening Guide

## Target Topologies

### 1. Docker Compose (Self-Hosted Single Node / Staging)
Includes PostgreSQL (`pgvector`), Redis, FastAPI API (`8000`), Nginx Frontend (`3000 -> 8080`), optional Redis Background Worker (`worker` profile), and optional local Ollama (`ollama` profile):

```bash
# Core API + UI + Postgres + Redis
docker compose up --build

# Include async Redis background worker for continuous smoke sweeps & embedding reindex
docker compose --profile worker up --build

# Include local open-weights Ollama runtime
docker compose --profile worker --profile ollama up --build
```

### 2. Cloud Run + Managed PostgreSQL + Firebase Hosting
1. **Managed PostgreSQL (`pgvector`):** Provision Cloud SQL PostgreSQL 16 (or Supabase/Neon) and run database migrations:
   ```bash
   cd backend
   DATABASE_URL="postgresql+asyncpg://<user>:<pass>@<host>:5432/ai_qa_release_engineer" alembic upgrade head
   ```
2. **Backend API on Cloud Run:**
   Build and deploy `backend/Dockerfile` with production security flags:
   - `APP_ENV=production`
   - `AUTH_SECRET_KEY=<unique-32+-byte-random-secret>`
   - `AUTH_REQUIRE_TOKEN=true`
   - `CORS_ORIGINS=https://your-domain.example`
   - `LLM_REDACT_PII_FOR_CLOUD=true`
   - `GITHUB_WEBHOOK_SECRET=<hmac-secret>`
   - `RATE_LIMIT_ENABLED=true`
   - `OTEL_ENABLED=true`
   - Probes: `/api/v1/health/live` (liveness) and `/api/v1/health/ready` (readiness).
3. **Frontend on Firebase Hosting / CDN:**
   Build `frontend/` (`npm ci && npm run build`) and configure `/api/**` rewrites to the Cloud Run service URL.

## Production Security Checklist
- [ ] `APP_ENV=production` verified (disables `/api/v1/auth/token` dev issuance and enforces `validate_production_security()`).
- [ ] `AUTH_SECRET_KEY` replaced with >= 32-byte cryptographically random secret.
- [ ] `CORS_ORIGINS` restricted to explicit frontend origin(s) (no `*`).
- [ ] `GITHUB_WEBHOOK_SECRET` set so `POST /api/v1/integrations/github/webhook` requires valid `X-Hub-Signature-256`.
- [ ] Service automation uses scoped `X-API-Key` credentials minted via `POST /api/v1/auth/api-keys`.
- [ ] Scrape `/api/v1/metrics` or `/metrics` with Prometheus and monitor `rate_limit_rejections_total` + `http_requests_total`.
