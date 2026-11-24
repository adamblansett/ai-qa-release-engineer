from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FlowStep(BaseModel):
    action: Literal[
        "navigate",
        "fill",
        "click",
        "assert_visible",
        "assert_text",
        "assert_url",
        "api_check",
    ]
    target: str = Field(default="", max_length=300)
    value: str = Field(default="", max_length=500)
    expected: str = Field(default="", max_length=500)


class OpenApiSynthesizeRequest(BaseModel):
    suite_name: str = Field(min_length=2, max_length=200)
    spec_text: str = Field(min_length=10, max_length=200000)
    framework: Literal["playwright", "pytest"] = "playwright"
    target_base_url: str = Field(default="http://localhost:8000", max_length=500)
    include_negative_cases: bool = True
    include_auth_cases: bool = True


class UserFlowSynthesizeRequest(BaseModel):
    suite_name: str = Field(min_length=2, max_length=200)
    flow_name: str = Field(min_length=2, max_length=200)
    target_base_url: str = Field(default="http://localhost:3000", max_length=500)
    steps: list[FlowStep] = Field(min_length=1, max_length=40)


class GeneratedTestCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_key: str
    title: str
    category: str
    http_method: str
    endpoint_or_route: str
    assertions_json: list[str]
    code_snippet: str
    priority: str
    created_at: datetime


class TestSuiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    source_type: str
    framework: str
    target_base_url: str
    spec_hash: str
    case_count: int
    status: str
    generated_code: str
    ai_summary: str
    approval_id: str | None = None
    created_by: str
    created_at: datetime
    cases: list[GeneratedTestCaseOut] = Field(default_factory=list)
