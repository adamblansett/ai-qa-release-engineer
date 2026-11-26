from typing import Any, Literal

from pydantic import BaseModel, Field


class GitHubWebhookResponse(BaseModel):
    accepted: bool
    event: str
    action_taken: str
    created_ci_run_id: str | None = None
    linked_release_id: str | None = None


class GitHubCheckPublishRequest(BaseModel):
    repository: str = Field(min_length=3, max_length=200)
    head_sha: str = Field(min_length=4, max_length=64)
    release_id: str | None = None
    ci_run_id: str | None = None
    check_name: str = Field(default="AI QA & Release Gate", max_length=120)
    dry_run: bool = True


class GitHubCheckPublishResponse(BaseModel):
    published: bool
    mode: Literal["dry_run", "github_api"]
    repository: str
    head_sha: str
    conclusion: Literal["success", "failure", "action_required"]
    title: str
    summary_markdown: str
    external_url: str | None = None
    api_response: dict[str, Any] = Field(default_factory=dict)
