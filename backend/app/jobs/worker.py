import asyncio

import structlog
from redis.asyncio import Redis

from app.core.auth import Actor
from app.core.config import get_settings
from app.db.models import BackgroundJob
from app.db.session import build_engine, build_session_factory, init_db
from app.jobs.runner import QUEUE_KEY, execute_job
from app.llm.router import LLMRouter

logger = structlog.get_logger(__name__)


async def run_worker_loop() -> None:
    """Consume queued QA/release jobs from Redis and execute them against the database."""
    settings = get_settings()
    engine = build_engine(settings.database_url)
    await init_db(engine)
    session_factory = build_session_factory(engine)
    llm_router = LLMRouter(settings)
    redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    worker_actor = Actor(
        email="worker@ai-qa-release.local",
        role="admin",
        auth_method="worker",
    )

    logger.info("qa_worker_started", queue=QUEUE_KEY, redis_url=settings.redis_url)
    try:
        while True:
            item = await redis_client.blpop([QUEUE_KEY], timeout=5)
            if item is None:
                continue
            _, job_id = item
            async with session_factory() as session:
                job = await session.get(BackgroundJob, str(job_id))
                if job is None:
                    logger.warning("qa_worker_missing_job", job_id=job_id)
                    continue
                await execute_job(
                    session,
                    job=job,
                    settings=settings,
                    llm_router=llm_router,
                    actor=worker_actor,
                )
    finally:
        await redis_client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_worker_loop())
