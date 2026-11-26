from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import Actor, get_current_actor, require_roles
from app.core.config import Settings, get_settings
from app.db.models import BackgroundJob
from app.db.session import get_db
from app.jobs.runner import QUEUE_KEY, execute_job
from app.jobs.schemas import BackgroundJobOut, JobEnqueueRequest
from app.llm.router import LLMRouter, get_llm_router

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _resolve_settings(request: Request) -> Settings:
    cfg = getattr(request.app.state, "settings", None)
    return cfg if isinstance(cfg, Settings) else get_settings()


@router.get("", response_model=list[BackgroundJobOut])
async def list_jobs(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[BackgroundJob]:
    """List background QA and release jobs newest first."""
    _ = actor
    stmt = select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(100)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{job_id}", response_model=BackgroundJobOut)
async def get_job(
    job_id: str,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> BackgroundJob:
    """Fetch status and results for a single background job."""
    _ = actor
    job = await db.get(BackgroundJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Background job '{job_id}' not found.",
        )
    return job


@router.post("/enqueue", response_model=BackgroundJobOut, status_code=status.HTTP_201_CREATED)
async def enqueue_job(
    payload: JobEnqueueRequest,
    request: Request,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> BackgroundJob:
    """Enqueue a QA/release job (executes inline in dev/CI or pushes to Redis worker queue)."""
    settings = _resolve_settings(request)
    job = BackgroundJob(
        job_type=payload.job_type,
        execution_mode=settings.task_execution_mode,
        status="queued",
        payload_json=payload.payload_json,
        requested_by=actor.email,
    )
    db.add(job)
    await db.flush()

    if settings.task_execution_mode == "redis":
        redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis_client.rpush(QUEUE_KEY, job.id)
        finally:
            await redis_client.aclose()
        await record_audit_event(
            db,
            event_type="job.queued",
            actor=actor,
            entity_type="background_job",
            entity_id=job.id,
            action=f"enqueue_{job.job_type}",
            details={"execution_mode": "redis"},
        )
        await db.commit()
        await db.refresh(job)
        return job

    return await execute_job(
        db,
        job=job,
        settings=settings,
        llm_router=llm_router,
        actor=actor,
    )
