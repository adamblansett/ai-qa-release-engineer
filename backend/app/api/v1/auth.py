from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import (
    Actor,
    ActorRole,
    create_access_token,
    generate_api_key,
    get_current_actor,
    require_roles,
)
from app.core.config import Settings, get_settings
from app.db.base import utcnow
from app.db.models import ApiKey
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenIssueRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: ActorRole = "qa_engineer"
    ttl_seconds: int = Field(default=3600, ge=60, le=86400)


class TokenIssueResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    actor: Actor


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    role: ActorRole = "qa_engineer"
    owner_email: str = Field(min_length=3, max_length=254)


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    key_prefix: str
    role: str
    owner_email: str
    created_by: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyCreateResponse(ApiKeyOut):
    raw_key: str


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


@router.get("/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(
    actor: Actor = Depends(require_roles("release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> list[ApiKey]:
    """List provisioned API keys (requires release_manager or admin)."""
    _ = actor
    stmt = select(ApiKey).order_by(ApiKey.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())


@router.post("/api-keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    actor: Actor = Depends(require_roles("release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    """Provision a scoped API key for headless CI/CD pipelines or automation."""
    raw_key, key_prefix, key_digest = generate_api_key()
    row = ApiKey(
        name=payload.name.strip(),
        key_prefix=key_prefix,
        key_hash=key_digest,
        role=payload.role,
        owner_email=payload.owner_email.strip(),
        created_by=actor.email,
    )
    db.add(row)
    await db.flush()

    await record_audit_event(
        db,
        event_type="auth.api_key_created",
        actor=actor,
        entity_type="api_key",
        entity_id=row.id,
        action="create_api_key",
        details={
            "name": row.name,
            "key_prefix": row.key_prefix,
            "role": row.role,
            "owner_email": row.owner_email,
        },
    )
    await db.commit()
    await db.refresh(row)

    return ApiKeyCreateResponse(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        role=row.role,
        owner_email=row.owner_email,
        created_by=row.created_by,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        raw_key=raw_key,
    )


@router.delete("/api-keys/{key_id}", response_model=ApiKeyOut)
async def revoke_api_key(
    key_id: str,
    actor: Actor = Depends(require_roles("release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """Revoke an existing API key immediately."""
    row = await db.get(ApiKey, key_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key '{key_id}' not found.",
        )
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        await record_audit_event(
            db,
            event_type="auth.api_key_revoked",
            actor=actor,
            entity_type="api_key",
            entity_id=row.id,
            action="revoke_api_key",
            details={"name": row.name, "key_prefix": row.key_prefix},
        )
        await db.commit()
        await db.refresh(row)
    return row
