import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit.schemas import ApprovalRequestOut
from app.audit.service import create_approval_request, record_audit_event
from app.core.auth import Actor, get_current_actor, require_roles
from app.db.models import ApprovalRequest, GeneratedTestCase, TestSuite
from app.db.session import get_db
from app.llm.router import LLMRouter, get_llm_router
from app.testgen.schemas import (
    OpenApiSynthesizeRequest,
    TestSuiteOut,
    UserFlowSynthesizeRequest,
)
from app.testgen.synthesizer import synthesize_from_openapi, synthesize_from_user_flow

router = APIRouter(prefix="/testgen", tags=["testgen"])


@router.get("/suites", response_model=list[TestSuiteOut])
async def list_test_suites(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[TestSuite]:
    """List synthesized test suites newest first."""
    _ = actor
    stmt = (
        select(TestSuite)
        .options(selectinload(TestSuite.cases))
        .order_by(TestSuite.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


@router.get("/suites/{suite_id}", response_model=TestSuiteOut)
async def get_test_suite(
    suite_id: str,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> TestSuite:
    """Fetch a single synthesized test suite with all generated cases."""
    _ = actor
    stmt = (
        select(TestSuite)
        .options(selectinload(TestSuite.cases))
        .where(TestSuite.id == suite_id)
    )
    suite = (await db.execute(stmt)).scalar_one_or_none()
    if suite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test suite '{suite_id}' not found.",
        )
    return suite


@router.post(
    "/synthesize/openapi",
    response_model=TestSuiteOut,
    status_code=status.HTTP_201_CREATED,
)
async def synthesize_openapi_suite(
    payload: OpenApiSynthesizeRequest,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> TestSuite:
    """Synthesize Playwright or pytest API contract tests from an OpenAPI JSON/YAML spec."""
    try:
        cases_spec, full_code, spec_hash = synthesize_from_openapi(
            suite_name=payload.suite_name,
            spec_text=payload.spec_text,
            framework=payload.framework,
            target_base_url=payload.target_base_url,
            include_negative_cases=payload.include_negative_cases,
            include_auth_cases=payload.include_auth_cases,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid OpenAPI specification: {exc}",
        ) from exc

    llm_resp = await llm_router.generate(
        prompt=(
            f"Suite '{payload.suite_name}' ({payload.framework}) synthesized "
            f"{len(cases_spec)} cases targeting {payload.target_base_url}."
        ),
        system_prompt="Summarize QA test synthesis coverage concisely.",
        task_type="testgen_synthesis",
    )

    suite = TestSuite(
        name=payload.suite_name.strip(),
        source_type="openapi",
        framework=payload.framework,
        target_base_url=payload.target_base_url.strip(),
        source_spec_raw=payload.spec_text,
        spec_hash=spec_hash,
        case_count=len(cases_spec),
        status="draft",
        generated_code=full_code,
        ai_summary=llm_resp.content,
        created_by=actor.email,
    )
    db.add(suite)
    await db.flush()

    for case in cases_spec:
        db.add(
            GeneratedTestCase(
                suite_id=suite.id,
                case_key=case.case_key,
                title=case.title,
                category=case.category,
                http_method=case.http_method,
                endpoint_or_route=case.endpoint_or_route,
                assertions_json=case.assertions,
                code_snippet=case.code_snippet,
                priority=case.priority,
            )
        )

    await record_audit_event(
        db,
        event_type="testgen.synthesized",
        actor=actor,
        entity_type="test_suite",
        entity_id=suite.id,
        action="synthesize_openapi",
        details={
            "suite_name": suite.name,
            "framework": suite.framework,
            "case_count": len(cases_spec),
            "llm_provider": llm_resp.provider,
        },
    )
    await db.commit()

    stmt = (
        select(TestSuite)
        .options(selectinload(TestSuite.cases))
        .where(TestSuite.id == suite.id)
    )
    return (await db.execute(stmt)).scalar_one()


@router.post("/synthesize/flow", response_model=TestSuiteOut, status_code=status.HTTP_201_CREATED)
async def synthesize_flow_suite(
    payload: UserFlowSynthesizeRequest,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> TestSuite:
    """Synthesize Playwright E2E user journey tests from structured steps."""
    cases_spec, full_code, spec_hash = synthesize_from_user_flow(
        suite_name=payload.suite_name,
        flow_name=payload.flow_name,
        target_base_url=payload.target_base_url,
        steps=payload.steps,
    )

    llm_resp = await llm_router.generate(
        prompt=(
            f"User flow suite '{payload.suite_name}' for '{payload.flow_name}' "
            f"generated {len(cases_spec)} Playwright tests across {len(payload.steps)} steps."
        ),
        system_prompt="Summarize Playwright E2E coverage concisely.",
        task_type="testgen_synthesis",
    )

    suite = TestSuite(
        name=payload.suite_name.strip(),
        source_type="user_flow",
        framework="playwright",
        target_base_url=payload.target_base_url.strip(),
        source_spec_raw=json.dumps([s.model_dump() for s in payload.steps]),
        spec_hash=spec_hash,
        case_count=len(cases_spec),
        status="draft",
        generated_code=full_code,
        ai_summary=llm_resp.content,
        created_by=actor.email,
    )
    db.add(suite)
    await db.flush()

    for case in cases_spec:
        db.add(
            GeneratedTestCase(
                suite_id=suite.id,
                case_key=case.case_key,
                title=case.title,
                category=case.category,
                http_method=case.http_method,
                endpoint_or_route=case.endpoint_or_route,
                assertions_json=case.assertions,
                code_snippet=case.code_snippet,
                priority=case.priority,
            )
        )

    await record_audit_event(
        db,
        event_type="testgen.synthesized",
        actor=actor,
        entity_type="test_suite",
        entity_id=suite.id,
        action="synthesize_flow",
        details={
            "suite_name": suite.name,
            "flow_name": payload.flow_name,
            "case_count": len(cases_spec),
        },
    )
    await db.commit()

    stmt = (
        select(TestSuite)
        .options(selectinload(TestSuite.cases))
        .where(TestSuite.id == suite.id)
    )
    return (await db.execute(stmt)).scalar_one()


@router.post("/suites/{suite_id}/request-approval", response_model=ApprovalRequestOut)
async def request_suite_publish_approval(
    suite_id: str,
    actor: Actor = Depends(require_roles("qa_engineer", "release_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequest:
    """Submit a synthesized test suite for human-in-the-loop publication approval."""
    suite = await db.get(TestSuite, suite_id)
    if suite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test suite '{suite_id}' not found.",
        )
    if suite.status == "pending_approval" and suite.approval_id:
        existing = await db.get(ApprovalRequest, suite.approval_id)
        if existing is not None:
            return existing

    approval = await create_approval_request(
        db,
        entity_type="test_suite_publish",
        entity_id=suite.id,
        action_requested=(
            f"Publish {suite.framework} suite '{suite.name}' ({suite.case_count} cases)"
        ),
        summary=(
            f"Publish synthesized {suite.source_type} suite '{suite.name}' "
            f"for {suite.target_base_url}."
        ),
        risk_level="low",
        requested_by=actor.email,
    )
    suite.status = "pending_approval"
    suite.approval_id = approval.id

    await record_audit_event(
        db,
        event_type="testgen.approval_requested",
        actor=actor,
        entity_type="test_suite",
        entity_id=suite.id,
        action="request_publish_approval",
        details={"approval_id": approval.id, "suite_name": suite.name},
    )
    await db.commit()
    await db.refresh(approval)
    return approval
