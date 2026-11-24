import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import yaml

from app.testgen.schemas import FlowStep

HTTP_METHODS = ("get", "post", "put", "patch", "delete")


@dataclass(frozen=True)
class SynthesizedCaseSpec:
    case_key: str
    title: str
    category: str
    http_method: str
    endpoint_or_route: str
    assertions: list[str]
    code_snippet: str
    priority: str


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return cleaned or "case"


def parse_openapi_spec(raw_spec: str) -> dict[str, Any]:
    """Parse JSON or YAML OpenAPI specification and validate top-level paths."""
    stripped = raw_spec.strip()
    if not stripped:
        raise ValueError("OpenAPI specification cannot be empty.")

    parsed: Any = json.loads(stripped) if stripped.startswith("{") else yaml.safe_load(stripped)

    if not isinstance(parsed, dict):
        raise ValueError("OpenAPI specification must deserialize to a mapping object.")
    paths = parsed.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError("OpenAPI specification must define a non-empty 'paths' object.")
    return parsed


def _resolve_ref(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#/"):
        return {}
    node: Any = root
    for part in ref[2:].split("/"):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return {}
    return node if isinstance(node, dict) else {}


def _resolve_schema(
    schema: dict[str, Any] | None,
    root: dict[str, Any],
    depth: int = 0,
) -> dict[str, Any]:
    if not isinstance(schema, dict) or depth > 6:
        return {}
    ref = schema.get("$ref")
    if isinstance(ref, str):
        resolved = _resolve_ref(ref, root)
        return _resolve_schema(resolved, root, depth + 1)
    if "allOf" in schema and isinstance(schema["allOf"], list):
        merged: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for sub in schema["allOf"]:
            sub_resolved = _resolve_schema(sub, root, depth + 1)
            if isinstance(sub_resolved.get("properties"), dict):
                merged["properties"].update(sub_resolved["properties"])
            if isinstance(sub_resolved.get("required"), list):
                merged["required"].extend(sub_resolved["required"])
        return merged
    return schema


def _sample_value(
    schema: dict[str, Any], field_name: str, root: dict[str, Any], depth: int = 0
) -> Any:
    if depth > 4:
        return "sample"
    resolved = _resolve_schema(schema, root, depth)
    if "example" in resolved:
        return resolved["example"]
    enum_vals = resolved.get("enum")
    if isinstance(enum_vals, list) and enum_vals:
        return enum_vals[0]

    schema_type = resolved.get("type", "string")
    fmt = str(resolved.get("format", "")).lower()
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 42.5
    if schema_type == "boolean":
        return True
    if schema_type == "array":
        items = resolved.get("items")
        if isinstance(items, dict):
            return [_sample_value(items, field_name, root, depth + 1)]
        return ["sample-item"]
    if schema_type == "object" or "properties" in resolved:
        props = resolved.get("properties")
        if not isinstance(props, dict):
            return {}
        return {
            str(k): _sample_value(v, str(k), root, depth + 1)
            for k, v in props.items()
            if isinstance(v, dict)
        }
    if fmt == "email" or "email" in field_name.lower():
        return "qa.bot@example.com"
    if fmt == "uuid":
        return "00000000-0000-4000-8000-000000000001"
    if fmt in {"date-time", "datetime"}:
        return "2026-11-24T00:00:00Z"
    if fmt == "uri":
        return "https://example.com/resource"
    return f"sample_{_slugify(field_name)}"


def _build_request_payload(
    operation: dict[str, Any], root: dict[str, Any]
) -> dict[str, Any] | None:
    req_body = operation.get("requestBody")
    if not isinstance(req_body, dict):
        return None
    if "$ref" in req_body:
        req_body = _resolve_ref(str(req_body["$ref"]), root)
    content = req_body.get("content")
    if not isinstance(content, dict):
        return None
    json_media = content.get("application/json")
    if not isinstance(json_media, dict):
        return None
    schema = json_media.get("schema")
    if not isinstance(schema, dict):
        return None
    sample = _sample_value(schema, "payload", root)
    return sample if isinstance(sample, dict) else {"value": sample}


def _extract_response_info(
    operation: dict[str, Any],
    root: dict[str, Any],
) -> tuple[int, list[str], dict[str, Any]]:
    responses = operation.get("responses")
    if not isinstance(responses, dict) or not responses:
        return 200, ["status == 200"], {}

    preferred_code = 200
    selected_resp: dict[str, Any] = {}
    for code in ("200", "201", "202", "204"):
        if code in responses and isinstance(responses[code], dict):
            preferred_code = int(code)
            selected_resp = responses[code]
            break
    if not selected_resp:
        first_key, first_val = next(iter(responses.items()))
        if str(first_key).isdigit():
            preferred_code = int(first_key)
        if isinstance(first_val, dict):
            selected_resp = first_val

    assertions = [f"status == {preferred_code}"]
    props_meta: dict[str, Any] = {}
    content = selected_resp.get("content")
    if isinstance(content, dict) and isinstance(content.get("application/json"), dict):
        schema = _resolve_schema(content["application/json"].get("schema"), root)
        required = schema.get("required") or []
        if isinstance(required, list):
            for field in required:
                assertions.append(f"body has required field '{field}'")
        props = schema.get("properties")
        if isinstance(props, dict):
            for prop_name, prop_def in props.items():
                if isinstance(prop_def, dict):
                    resolved_prop = _resolve_schema(prop_def, root)
                    ptype = resolved_prop.get("type")
                    if isinstance(ptype, str):
                        assertions.append(f"body.{prop_name} is type '{ptype}'")
                        props_meta[str(prop_name)] = ptype
    return preferred_code, assertions, props_meta


def _format_path_with_params(path: str, operation: dict[str, Any]) -> str:
    resolved_path = path
    params = operation.get("parameters")
    if isinstance(params, list):
        for param in params:
            if not isinstance(param, dict):
                continue
            if param.get("in") == "path":
                name = str(param.get("name", "id"))
                raw_schema = param.get("schema")
                schema: dict[str, Any] = raw_schema if isinstance(raw_schema, dict) else {}
                val = "1" if schema.get("type") == "integer" else f"sample-{_slugify(name)}"
                resolved_path = resolved_path.replace(f"{{{name}}}", str(val))
    return re.sub(r"\{([^}]+)\}", r"sample_\1", resolved_path)


def _render_playwright_case(
    *,
    title: str,
    method: str,
    url_path: str,
    expected_statuses: list[int],
    request_payload: dict[str, Any] | None,
    required_fields: list[str],
    auth_header_omit: bool = False,
) -> str:
    method_lower = method.lower()
    req_opts: list[str] = []
    if request_payload is not None:
        req_opts.append(f"data: {json.dumps(request_payload)}")
    if not auth_header_omit:
        req_opts.append("headers: { Accept: 'application/json' }")
    opts_block = f", {{ {', '.join(req_opts)} }}" if req_opts else ""

    lines = [
        f"test({json.dumps(title)}, async ({{ request }}) => {{",
        f"  const response = await request.{method_lower}({json.dumps(url_path)}{opts_block});",
    ]
    if len(expected_statuses) == 1:
        lines.append(f"  expect(response.status()).toBe({expected_statuses[0]});")
    else:
        lines.append(
            f"  expect({json.dumps(expected_statuses)}).toContain(response.status());"
        )
    if required_fields and all(code < 400 for code in expected_statuses):
        lines.append("  const payload = await response.json();")
        for field in required_fields:
            lines.append(f"  expect(payload).toHaveProperty({json.dumps(field)});")
    lines.append("});")
    return "\n".join(lines)


def _render_pytest_case(
    *,
    func_name: str,
    method: str,
    url_path: str,
    expected_statuses: list[int],
    request_payload: dict[str, Any] | None,
    required_fields: list[str],
) -> str:
    method_lower = method.lower()
    call_args = [json.dumps(url_path)]
    if request_payload is not None:
        call_args.append(f"json={json.dumps(request_payload)}")
    lines = [
        "@pytest.mark.asyncio",
        f"async def test_{func_name}(api_client: httpx.AsyncClient) -> None:",
        f"    response = await api_client.{method_lower}({', '.join(call_args)})",
    ]
    if len(expected_statuses) == 1:
        lines.append(f"    assert response.status_code == {expected_statuses[0]}")
    else:
        lines.append(f"    assert response.status_code in {tuple(expected_statuses)}")
    if required_fields and all(code < 400 for code in expected_statuses):
        lines.append("    body = response.json()")
        for field in required_fields:
            lines.append(f"    assert {json.dumps(field)} in body")
    return "\n".join(lines)


def synthesize_from_openapi(
    *,
    suite_name: str,
    spec_text: str,
    framework: str,
    target_base_url: str,
    include_negative_cases: bool,
    include_auth_cases: bool,
) -> tuple[list[SynthesizedCaseSpec], str, str]:
    """Synthesize deterministic contract/API test cases from an OpenAPI JSON/YAML spec."""
    spec = parse_openapi_spec(spec_text)
    spec_hash = hashlib.sha256(spec_text.encode("utf-8")).hexdigest()
    global_security = bool(spec.get("security"))

    cases: list[SynthesizedCaseSpec] = []
    paths = spec["paths"]

    for raw_path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue

            url_path = _format_path_with_params(str(raw_path), op)
            op_id = str(op.get("operationId") or f"{method}_{_slugify(str(raw_path))}")
            req_payload = _build_request_payload(op, spec)
            ok_status, assertions, _props = _extract_response_info(op, spec)
            req_fields = [
                a.split("'")[1]
                for a in assertions
                if a.startswith("body has required field '")
            ]

            happy_title = f"{method.upper()} {raw_path} returns {ok_status} with valid schema"
            if framework == "playwright":
                snippet = _render_playwright_case(
                    title=happy_title,
                    method=method,
                    url_path=url_path,
                    expected_statuses=[ok_status],
                    request_payload=req_payload,
                    required_fields=req_fields,
                )
            else:
                snippet = _render_pytest_case(
                    func_name=_slugify(f"{op_id}_happy"),
                    method=method,
                    url_path=url_path,
                    expected_statuses=[ok_status],
                    request_payload=req_payload,
                    required_fields=req_fields,
                )
            cases.append(
                SynthesizedCaseSpec(
                    case_key=f"{_slugify(op_id)}_happy",
                    title=happy_title,
                    category="happy_path",
                    http_method=method.upper(),
                    endpoint_or_route=str(raw_path),
                    assertions=assertions,
                    code_snippet=snippet,
                    priority="P0",
                )
            )

            has_required_params = any(
                isinstance(p, dict) and p.get("required") and p.get("in") in {"query", "header"}
                for p in (op.get("parameters") or [])
            )
            if include_negative_cases and (req_payload is not None or has_required_params):
                neg_title = f"{method.upper()} {raw_path} rejects malformed payload"
                bad_payload: dict[str, Any] | None = {} if req_payload is not None else None
                neg_assertions = ["status in [400, 422]", "validation error detail present"]
                if framework == "playwright":
                    neg_snippet = _render_playwright_case(
                        title=neg_title,
                        method=method,
                        url_path=url_path,
                        expected_statuses=[400, 422],
                        request_payload=bad_payload,
                        required_fields=[],
                    )
                else:
                    neg_snippet = _render_pytest_case(
                        func_name=_slugify(f"{op_id}_validation_error"),
                        method=method,
                        url_path=url_path,
                        expected_statuses=[400, 422],
                        request_payload=bad_payload,
                        required_fields=[],
                    )
                cases.append(
                    SynthesizedCaseSpec(
                        case_key=f"{_slugify(op_id)}_validation",
                        title=neg_title,
                        category="validation",
                        http_method=method.upper(),
                        endpoint_or_route=str(raw_path),
                        assertions=neg_assertions,
                        code_snippet=neg_snippet,
                        priority="P1",
                    )
                )

            requires_auth = bool(op.get("security")) or (
                global_security and op.get("security") != []
            )
            if include_auth_cases and requires_auth:
                auth_title = f"{method.upper()} {raw_path} enforces authentication (401/403)"
                auth_assertions = ["status in [401, 403]", "unauthenticated access denied"]
                if framework == "playwright":
                    auth_snippet = _render_playwright_case(
                        title=auth_title,
                        method=method,
                        url_path=url_path,
                        expected_statuses=[401, 403],
                        request_payload=req_payload,
                        required_fields=[],
                        auth_header_omit=True,
                    )
                else:
                    auth_snippet = _render_pytest_case(
                        func_name=_slugify(f"{op_id}_auth_guard"),
                        method=method,
                        url_path=url_path,
                        expected_statuses=[401, 403],
                        request_payload=req_payload,
                        required_fields=[],
                    )
                cases.append(
                    SynthesizedCaseSpec(
                        case_key=f"{_slugify(op_id)}_auth_guard",
                        title=auth_title,
                        category="auth_guard",
                        http_method=method.upper(),
                        endpoint_or_route=str(raw_path),
                        assertions=auth_assertions,
                        code_snippet=auth_snippet,
                        priority="P0",
                    )
                )

    if not cases:
        raise ValueError("No supported HTTP operations (GET/POST/PUT/PATCH/DELETE) found in spec.")

    if framework == "playwright":
        header = (
            "import { test, expect } from '@playwright/test';\n\n"
            f"// Synthesized Suite: {suite_name}\n"
            f"test.use({{ baseURL: {json.dumps(target_base_url)} }});\n\n"
        )
    else:
        header = (
            "import httpx\nimport pytest\nimport pytest_asyncio\n\n"
            f"# Synthesized Suite: {suite_name}\n"
            f"BASE_URL = {json.dumps(target_base_url)}\n\n"
            "@pytest_asyncio.fixture\n"
            "async def api_client() -> httpx.AsyncClient:\n"
            "    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:\n"
            "        yield client\n\n"
        )

    full_code = header + "\n\n".join(case.code_snippet for case in cases) + "\n"
    return cases, full_code, spec_hash


def synthesize_from_user_flow(
    *,
    suite_name: str,
    flow_name: str,
    target_base_url: str,
    steps: list[FlowStep],
) -> tuple[list[SynthesizedCaseSpec], str, str]:
    """Synthesize Playwright E2E journey and edge-case tests from structured user flow steps."""
    canonical = json.dumps(
        {
            "suite_name": suite_name,
            "flow_name": flow_name,
            "target_base_url": target_base_url,
            "steps": [s.model_dump() for s in steps],
        },
        sort_keys=True,
    )
    spec_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    body_lines: list[str] = []
    assertions: list[str] = []
    primary_route = "/"

    for idx, step in enumerate(steps):
        if step.action == "navigate":
            target = step.target or "/"
            if idx == 0:
                primary_route = target
            body_lines.append(f"  await page.goto({json.dumps(target)});")
            assertions.append(f"navigates to {target}")
        elif step.action == "fill":
            body_lines.append(
                f"  await page.locator({json.dumps(step.target)}).fill({json.dumps(step.value)});"
            )
        elif step.action == "click":
            body_lines.append(f"  await page.locator({json.dumps(step.target)}).click();")
        elif step.action == "assert_visible":
            body_lines.append(
                f"  await expect(page.locator({json.dumps(step.target)})).toBeVisible();"
            )
            assertions.append(f"element '{step.target}' is visible")
        elif step.action == "assert_text":
            expected = step.expected or step.value
            body_lines.append(
                f"  await expect(page.locator({json.dumps(step.target)}))"
                f".toContainText({json.dumps(expected)});"
            )
            assertions.append(f"element '{step.target}' contains '{expected}'")
        elif step.action == "assert_url":
            expected = step.expected or step.target
            body_lines.append(
                f"  await expect(page).toHaveURL(new RegExp({json.dumps(expected)}));"
            )
            assertions.append(f"URL matches '{expected}'")
        elif step.action == "api_check":
            endpoint = step.target or "/api/v1/health"
            body_lines.append(f"  const apiRes = await page.request.get({json.dumps(endpoint)});")
            body_lines.append("  expect(apiRes.ok()).toBeTruthy();")
            assertions.append(f"API probe {endpoint} succeeds")

    if not assertions:
        assertions.append("flow completes without uncaught console/page errors")

    journey_title = f"E2E Journey: {flow_name}"
    journey_snippet = "\n".join(
        [
            f"test({json.dumps(journey_title)}, async ({{ page }}) => {{",
            "  const pageErrors: string[] = [];",
            "  page.on('pageerror', (err) => pageErrors.push(err.message));",
            *body_lines,
            "  expect(pageErrors).toEqual([]);",
            "});",
        ]
    )

    edge_title = f"E2E Resilience Guard: {flow_name} handles server error gracefully"
    edge_snippet = "\n".join(
        [
            f"test({json.dumps(edge_title)}, async ({{ page }}) => {{",
            "  await page.route('**/api/**', (route) =>",
            "    route.fulfill({ status: 503, body: "
            "JSON.stringify({ detail: 'Simulated outage' }) })",
            "  );",
            f"  await page.goto({json.dumps(primary_route)});",
            "  await expect(page.locator('body')).toBeVisible();",
            "});",
        ]
    )

    cases = [
        SynthesizedCaseSpec(
            case_key=f"{_slugify(flow_name)}_journey",
            title=journey_title,
            category="e2e_journey",
            http_method="FLOW",
            endpoint_or_route=primary_route,
            assertions=assertions,
            code_snippet=journey_snippet,
            priority="P0",
        ),
        SynthesizedCaseSpec(
            case_key=f"{_slugify(flow_name)}_resilience",
            title=edge_title,
            category="edge_case",
            http_method="FLOW",
            endpoint_or_route=primary_route,
            assertions=["handles 503 API degradation without crashing UI"],
            code_snippet=edge_snippet,
            priority="P1",
        ),
    ]

    full_code = (
        "import { test, expect } from '@playwright/test';\n\n"
        f"// Synthesized User Flow Suite: {suite_name}\n"
        f"test.use({{ baseURL: {json.dumps(target_base_url)} }});\n\n"
        + "\n\n".join(c.code_snippet for c in cases)
        + "\n"
    )
    return cases, full_code, spec_hash
