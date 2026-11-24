from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.auth import Actor, ActorRole, create_access_token, get_current_actor
from app.core.config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenIssueRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: ActorRole = "qa_engineer"
    ttl_seconds: int = Field(default=3600, ge=60, le=86400)


class TokenIssueResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    actor: Actor


@router.get("/me", response_model=Actor)
async def get_me(actor: Actor = Depends(get_current_actor)) -> Actor:
    """Return the resolved actor context for the current request."""
    return actor


@router.post("/token", response_model=TokenIssueResponse)
async def issue_dev_token(
    payload: TokenIssueRequest,
    request: Request,
) -> TokenIssueResponse:
    """Issue a signed dev/test HMAC token (disabled in production)."""
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        settings = get_settings()

    if settings.app_env.strip().lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development token issuance is disabled in production.",
        )

    token = create_access_token(
        email=payload.email.strip(),
        role=payload.role,
        secret_key=settings.auth_secret_key,
        ttl_seconds=payload.ttl_seconds,
    )
    return TokenIssueResponse(
        access_token=token,
        actor=Actor(email=payload.email.strip(), role=payload.role, auth_method="bearer_token"),
    )
