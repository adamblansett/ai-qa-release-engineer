import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.ci_triage.router import persist_ci_analysis
from app.ci_triage.schemas import CiLogAnalyzeRequest
from app.core.auth import Actor, require_roles
from app.core.config import Settings, get_settings
from app.db.models import CiBuildRun, ReleaseCandidate
from app.db.session import get_db
from app.integrations.github import (
    build_check_run_payload,
    post_github_check_run,
    verify_github_signature,
)
from app.integrations.schemas import (
    GitHubCheckPublishRequest,
    GitHubCheckPublishResponse,
    GitHubWebhookResponse,
)
from app.llm.router import LLMRouter, get_llm_router

router = APIRouter(prefix="/integrations/github", tags=["integrations"])


def _resolve_settings(request: Request) -> Settings:
    cfg = getattr(request.app.state, "settings", None)
    return cfg if isinstance(cfg, Settings) else get_settings()


@router.post("/webhook", response_model=GitHubWebhookResponse)
async def receive_github_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> GitHubWebhookResponse:
    """Ingest signed GitHub Actions workflow_run and deployment_status webhook events."""
    settings = _resolve_settings(request)
    raw_body = await request.body()
    event_name = request.headers.get("x-github-event", "ping").strip().lower()
    sig_header = request.headers.get("x-hub-signature-256", "").strip()

    is_prod = settings.app_env.strip().lower() == "production"
    if (settings.github_webhook_secret or is_prod) and not verify_github_signature(
        raw_body, sig_header, settings.github_webhook_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Hub-Signature-256 signature.",
        )

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON webhook payload: {exc}",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload must be a JSON object.",
        )

    webhook_actor = Actor(
        email="github-webhook@integrations.local",
        role="qa_engineer",
        auth_method="github_webhook",
    )

    if event_name == "ping":
        return GitHubWebhookResponse(
            accepted=True,
            event="ping",
            action_taken="pong",
        )

    if event_name == "workflow_run":
        wf = payload.get("workflow_run")
        wf_obj = wf if isinstance(wf, dict) else {}
        repo_obj = payload.get("repository")
        repo_name = (
            str(repo_obj.get("full_name") or "github-repo")
            if isinstance(repo_obj, dict)
            else "github-repo"
        )
        conclusion = str(wf_obj.get("conclusion") or "failure").lower()
        run_status: Literal["passed", "failed"] = (
            "passed" if conclusion in {"success", "neutral", "skipped"} else "failed"
        )
        branch = str(wf_obj.get("head_branch") or "main")
        sha = str(wf_obj.get("head_sha") or "0000000")[:64]
        job_name = str(wf_obj.get("name") or "workflow_run")
        log_excerpt = str(
            wf_obj.get("log_excerpt")
            or payload.get("log_excerpt")
            or (
                f"GitHub workflow_run '{job_name}' conclusion={conclusion}"
                if run_status == "passed"
                else f"AssertionError: GitHub workflow_run '{job_name}' failed ({conclusion})"
            )
        )
        ci_req = CiLogAnalyzeRequest(
            pipeline_name=repo_name,
            branch=branch,
            commit_sha=sha,
            job_name=job_name,
            status=run_status,
            duration_seconds=float(wf_obj.get("duration_seconds") or 0.0),
            raw_log=log_excerpt,
        )
        created = await persist_ci_analysis(
            db,
            payload=ci_req,
            actor=webhook_actor,
            settings=settings,
            llm_router=llm_router,
            event_type="github.workflow_run_ingested",
        )
        return GitHubWebhookResponse(
            accepted=True,
            event="workflow_run",
            action_taken=f"ingested_{created.status}",
            created_ci_run_id=created.id,
        )

    if event_name == "deployment_status":
        dep = payload.get("deployment")
        dep_status = payload.get("deployment_status")
        dep_obj = dep if isinstance(dep, dict) else {}
        status_obj = dep_status if isinstance(dep_status, dict) else {}
        sha = str(dep_obj.get("sha") or "")
        state = str(status_obj.get("state") or "pending").lower()

        linked_release = None
        if sha:
            linked_release = (
                await db.execute(
                    select(ReleaseCandidate).where(ReleaseCandidate.commit_sha == sha)
                )
            ).scalar_one_or_none()

        await record_audit_event(
            db,
            event_type="github.deployment_status",
            actor=webhook_actor,
            entity_type="release_candidate" if linked_release else "github_deployment",
            entity_id=linked_release.id if linked_release else (sha or "unknown"),
            action=f"deployment_{state}",
            details={
                "sha": sha,
                "state": state,
                "environment": str(dep_obj.get("environment") or ""),
            },
        )
        await db.commit()
        return GitHubWebhookResponse(
            accepted=True,
            event="deployment_status",
            action_taken=f"recorded_{state}",
            linked_release_id=linked_release.id if linked_release else None,
        )

    return GitHubWebhookResponse(
        accepted=True,
        event=event_name,
        action_taken="ignored_unhandled_event",
    )


@router.post("/publish-check", response_model=GitHubCheckPublishResponse)
async def publish_github_check(
    payload: GitHubCheckPublishRequest,
    request: Request,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> GitHubCheckPublishResponse:
    """Build and publish (or dry-run) a GitHub PR Check Run from release or CI triage state."""
    settings = _resolve_settings(request)
    release = await db.get(ReleaseCandidate, payload.release_id) if payload.release_id else None
    ci_run = await db.get(CiBuildRun, payload.ci_run_id) if payload.ci_run_id else None

    if payload.release_id and release is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release candidate '{payload.release_id}' not found.",
        )
    if payload.ci_run_id and ci_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CI build run '{payload.ci_run_id}' not found.",
        )

    conclusion, title, summary_md = build_check_run_payload(
        check_name=payload.check_name,
        head_sha=payload.head_sha,
        release=release,
        ci_run=ci_run,
    )

    api_response: dict[str, object] = {}
    mode: str = "dry_run"
    external_url: str | None = None

    if not payload.dry_run and settings.github_token.strip():
        try:
            api_response = await post_github_check_run(
                repository=payload.repository.strip(),
                head_sha=payload.head_sha.strip(),
                check_name=payload.check_name.strip(),
                conclusion=conclusion,
                title=title,
                summary_markdown=summary_md,
                settings=settings,
            )
            mode = "github_api"
            raw_url = api_response.get("html_url")
            external_url = str(raw_url) if raw_url else None
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"GitHub Check Run API call failed: {exc}",
            ) from exc

    await record_audit_event(
        db,
        event_type="github.check_published",
        actor=actor,
        entity_type="release_candidate" if release else "ci_build_run",
        entity_id=(release.id if release else (ci_run.id if ci_run else payload.head_sha)),
        action=f"publish_{mode}_{conclusion}",
        details={
            "repository": payload.repository,
            "head_sha": payload.head_sha,
            "conclusion": conclusion,
            "mode": mode,
        },
    )
    await db.commit()

    return GitHubCheckPublishResponse(
        published=True,
        mode="github_api" if mode == "github_api" else "dry_run",
        repository=payload.repository.strip(),
        head_sha=payload.head_sha.strip(),
        conclusion=conclusion,
        title=title,
        summary_markdown=summary_md,
        external_url=external_url,
        api_response=api_response,
    )
