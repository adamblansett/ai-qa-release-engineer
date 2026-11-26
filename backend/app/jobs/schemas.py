from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class JobEnqueueRequest(BaseModel):
    job_type: Literal["canary_smoke_sweep", "embedding_reindex", "regression_suite_run"]
    payload_json: dict[str, Any] = Field(default_factory=dict)


class BackgroundJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_type: str
    execution_mode: str
    status: str
    payload_json: dict[str, Any]
    result_json: dict[str, Any]
    error_message: str
    requested_by: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
