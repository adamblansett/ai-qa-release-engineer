from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.llm.router import LLMRouter, get_llm_router
from app.seed.demo_data import SeedResponse, seed_demo_dataset

router = APIRouter(prefix="/seed", tags=["seed"])


@router.post("/demo", response_model=SeedResponse)
async def run_demo_seed(
    request: Request,
    reset: bool = Query(default=False),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> SeedResponse:
    """Populate idempotent QA & Release demo dataset (reset requires release_manager or admin)."""
    if reset and actor.role not in {"release_manager", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Resetting demo dataset requires release_manager or admin role.",
        )
    if not reset and actor.role not in {"qa_engineer", "release_manager", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seeding demo dataset requires qa_engineer, release_manager, or admin role.",
        )

    cfg = getattr(request.app.state, "settings", None)
    settings = cfg if isinstance(cfg, Settings) else get_settings()

    return await seed_demo_dataset(
        db,
        llm_router=llm_router,
        settings=settings,
        actor=actor,
        reset=reset,
    )
