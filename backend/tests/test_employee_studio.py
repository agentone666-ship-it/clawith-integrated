"""Job readiness and creation guards, including the actual Agent mutation path."""

import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api import agents
from app.api.employee_studio import router
from app.core.security import get_current_user
from app.dao.base import tenant_context
from app.database import bind_session_context, get_db
from app.models.agent import Agent
from app.models.llm import LLMModel
from app.models.tenant import Tenant
from app.models.tool import AgentTool, Tool
from app.models.user import User
from app.schemas.employee_studio import EmployeeSpecification, GenerateSpecification
from app.schemas.schemas import AgentCreate
from app.services import employee_studio as studio


def specification(**changes) -> EmployeeSpecification:
    return EmployeeSpecification.model_validate(
        {
            "name": "订单跟踪员",
            "audience": "供应链团队",
            "objective": "核对订单交期",
            "responsibilities": ["核对授权订单"],
            "boundaries": ["未授权不修改订单"],
            "output_format": "订单、异常及证据",
            "acceptance_criteria": ["结论有证据"],
            "test_cases": [
                {"kind": kind, "input": "查询订单", "expected": "按授权范围查询", "reviewed": True}
                for kind in ("normal", "exception", "boundary")
            ],
            **changes,
        }
    )


def test_readiness_requires_complete_job_and_all_three_reviewed_categories():
    assert studio.check_readiness(specification()).ready
    assert not studio.check_readiness(EmployeeSpecification()).ready
    spec = specification()
    spec.test_cases[0].reviewed = False
    assert not studio.check_readiness(spec).ready
    spec = specification(test_cases=spec.test_cases[:2])
    assert not studio.check_readiness(spec).ready


def test_connection_requirements_and_employee_kind_are_not_access_grants():
    result = studio.check_readiness(
        specification(
            employee_kind="subsidiary",
            connections=[{"kind": "rpa", "description": "业务办理"}],
        )
    )
    assert result.ready
    assert len(result.warnings) == 2
    assert "只有当前实际提供且获授权的工具" in studio.compile_personality(
        specification(
            connections=[{"kind": "mcp", "description": "订单系统"}],
        )
    )


def test_incomplete_test_and_connection_notes_can_be_saved_but_cannot_create_an_employee():
    spec = specification(connections=[{"kind": "sdk_cli", "description": ""}])
    spec.test_cases[0].input = ""
    issues = studio.check_readiness(spec)
    assert not issues.ready
    assert {issue.field for issue in issues.issues} == {"test_cases", "connections"}


@pytest.mark.parametrize(
    "payload",
    [
        {"employee_blueprint_id": str(uuid.uuid4())},
        {"employee_blueprint_revision": 1},
        {"employee_blueprint_id": str(uuid.uuid4()), "employee_blueprint_revision": 1, "agent_type": "openclaw"},
    ],
)
def test_agent_schema_rejects_incomplete_or_remote_blueprint_creation(payload):
    with pytest.raises(ValidationError):
        AgentCreate(name="测试员工", **payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"employee_kind": "unknown"},
        {"objective": "x" * 3001},
        {"skill_ids": [str(uuid.uuid4()) for _ in range(21)]},
        {"execute_command": "anything"},
    ],
)
def test_specification_rejects_unknown_fields_types_and_unbounded_input(payload):
    with pytest.raises(ValidationError):
        specification(**payload)


@pytest.mark.asyncio
async def test_generator_never_accepts_model_review_flags_or_invented_capabilities():
    spec = specification(skill_ids=[uuid.uuid4()], tool_ids=[uuid.uuid4()])
    result = SimpleNamespace(
        content="```json\n" + spec.model_dump_json() + "\n```", tool_calls=(), retry_instruction=None
    )
    user = SimpleNamespace(tenant_id=uuid.uuid4())
    with (
        patch.object(studio, "load_active_model", AsyncMock(return_value=object())),
        patch.object(studio, "complete_llm_once", AsyncMock(return_value=result)) as complete,
    ):
        generated = await studio.generate_specification(
            AsyncMock(),
            user,
            GenerateSpecification(
                requirement="跟踪订单并整理报告",
                employee_kind="team",
                model_id=uuid.uuid4(),
            ),
        )
    assert generated.employee_kind == "team"
    assert generated.skill_ids == generated.tool_ids == []
    assert all(not case.reviewed for case in generated.test_cases)
    assert complete.call_args.kwargs["max_output_tokens"] == 5000


@pytest.mark.asyncio
async def test_generator_returns_actionable_failure_instead_of_inventing_a_draft():
    with (
        patch.object(studio, "load_active_model", AsyncMock(return_value=object())),
        patch.object(
            studio,
            "complete_llm_once",
            AsyncMock(return_value=SimpleNamespace(content="not json", tool_calls=(), retry_instruction=None)),
        ),
        pytest.raises(HTTPException) as error,
    ):
        await studio.generate_specification(
            AsyncMock(),
            SimpleNamespace(tenant_id=uuid.uuid4()),
            GenerateSpecification(
                requirement="整理业务分析报告",
                employee_kind="personal",
                model_id=uuid.uuid4(),
            ),
        )
    assert error.value.status_code == 502


@pytest_asyncio.fixture
async def harness():
    url = os.getenv("STUDIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set STUDIO_TEST_DATABASE_URL to an isolated migrated PostgreSQL database")
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        outer = await connection.begin()
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as db:
            tenant = Tenant(name="Studio test", slug=f"studio-{uuid.uuid4().hex}")
            db.add(tenant)
            await db.flush()
            user = User(tenant_id=tenant.id, display_name="岗位创建人", role="member")
            model = LLMModel(
                tenant_id=tenant.id,
                provider="openai",
                model="test-model",
                label="Test only",
                api_key_encrypted="unused",
            )
            db.add_all([user, model])
            await db.flush()
            app = FastAPI()
            app.include_router(router, prefix="/api")
            app.include_router(agents.router, prefix="/api")

            async def override_db():
                async with bind_session_context(db):
                    with tenant_context(user.tenant_id):
                        yield db
                        await db.commit()

            app.dependency_overrides[get_db] = override_db
            app.dependency_overrides[get_current_user] = lambda: user
            with (
                patch.object(agents, "check_agent_creation_quota", AsyncMock()),
                patch.object(agents, "ensure_access_granted_platform_relationships", AsyncMock()),
                patch.object(agents, "_background_agent_setup", AsyncMock()) as setup,
            ):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    yield SimpleNamespace(
                        client=client, db=db, app=app, user=user, tenant=tenant, model=model, setup=setup
                    )
        await outer.rollback()
    await engine.dispose()


async def create_draft(h, **changes):
    response = await h.client.post(
        "/api/employee-studio/blueprints",
        json={
            "requirement": "跟踪订单",
            "specification": specification(**changes).model_dump(mode="json"),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_persistent_draft_conflicts_and_review_invalidation(harness):
    h = harness
    draft = await create_draft(h)
    payload = {"requirement": draft["requirement"], "specification": draft["specification"], "expected_revision": 1}
    payload["specification"]["objective"] = "更新后的工作目标"
    saved = await h.client.put(f"/api/employee-studio/blueprints/{draft['id']}", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    assert all(not case["reviewed"] for case in saved.json()["specification"]["test_cases"])
    assert (await h.client.put(f"/api/employee-studio/blueprints/{draft['id']}", json=payload)).status_code == 409
    checks = await h.client.post(f"/api/employee-studio/blueprints/{draft['id']}/check")
    assert checks.status_code == 200
    assert not checks.json()["ready"]


@pytest.mark.asyncio
async def test_other_user_and_tenant_cannot_read_edit_or_create_from_draft(harness):
    h = harness
    draft = await create_draft(h)
    other = SimpleNamespace(id=uuid.uuid4(), tenant_id=h.tenant.id, role="member", quota_agent_ttl_hours=0)
    h.app.dependency_overrides[get_current_user] = lambda: other
    assert (await h.client.get(f"/api/employee-studio/blueprints/{draft['id']}")).status_code == 404
    assert (await h.client.get("/api/employee-studio/blueprints")).json() == []
    response = await h.client.post(
        "/api/agents/",
        json={
            "name": "其他用户员工",
            "employee_blueprint_id": draft["id"],
            "employee_blueprint_revision": 1,
            "primary_model_id": str(h.model.id),
        },
    )
    assert response.status_code == 404
    other.id = h.user.id
    other.tenant_id = uuid.uuid4()
    assert (await h.client.get(f"/api/employee-studio/blueprints/{draft['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_direct_agent_endpoint_cannot_bypass_readiness(harness):
    h = harness
    draft = await create_draft(h, boundaries=[])
    response = await h.client.post(
        "/api/agents/",
        json={
            "name": "试图绕过检查",
            "employee_blueprint_id": draft["id"],
            "employee_blueprint_revision": 1,
            "primary_model_id": str(h.model.id),
        },
    )
    assert response.status_code == 400
    assert (await h.db.execute(select(Agent.id).where(Agent.tenant_id == h.tenant.id))).scalars().all() == []
    h.setup.assert_not_awaited()


@pytest.mark.asyncio
async def test_creation_uses_saved_spec_and_freezes_snapshot_in_same_transaction(harness):
    h = harness
    tool = Tool(name=f"test-{uuid.uuid4().hex}", display_name="查询订单", tenant_id=h.tenant.id, enabled=True)
    h.db.add(tool)
    await h.db.flush()
    draft = await create_draft(h, tool_ids=[tool.id])
    request = {
        "name": "不应覆盖岗位",
        "employee_blueprint_id": draft["id"],
        "employee_blueprint_revision": 1,
        "primary_model_id": str(h.model.id),
        "personality": "不应覆盖",
        "permission_scope_type": "company",
    }
    response = await h.client.post("/api/agents/", json=request)
    assert response.status_code == 201, response.text
    agent_id = uuid.UUID(response.json()["id"])
    agent = await h.db.get(Agent, agent_id)
    assert agent.name == "订单跟踪员"
    assert agent.access_mode == "private"
    assert agent.autonomy_policy["execute_code"] == "L3"
    assert "核对订单交期" in h.setup.call_args.kwargs["personality"]
    assert h.setup.call_args.kwargs["boundaries"] == "未授权不修改订单"
    assert (await h.db.execute(select(AgentTool.tool_id).where(AgentTool.agent_id == agent_id))).scalar_one() == tool.id
    snapshot = await h.client.get(f"/api/employee-studio/blueprints/{draft['id']}")
    assert snapshot.json()["published_agent_id"] == str(agent_id)
    assert (await h.client.post("/api/agents/", json=request)).status_code == 409
    assert (
        await h.client.put(
            f"/api/employee-studio/blueprints/{draft['id']}",
            json={
                "requirement": draft["requirement"],
                "specification": draft["specification"],
                "expected_revision": 1,
            },
        )
    ).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("disabled", [False, True])
async def test_unavailable_tools_block_actual_agent_creation(harness, disabled):
    h = harness
    tool_id = uuid.uuid4()
    if disabled:
        h.db.add(
            Tool(
                id=tool_id, name=f"disabled-{tool_id}", display_name="不可用工具", tenant_id=h.tenant.id, enabled=False
            )
        )
        await h.db.flush()
    draft = await create_draft(h, tool_ids=[tool_id])
    response = await h.client.post(
        "/api/agents/",
        json={
            "name": "测试员工",
            "employee_blueprint_id": draft["id"],
            "employee_blueprint_revision": 1,
            "primary_model_id": str(h.model.id),
        },
    )
    assert response.status_code == 400
    h.setup.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_tenant_capabilities_are_hidden_and_rejected_at_creation(harness):
    h = harness
    tenant = Tenant(name="Another company", slug=f"foreign-{uuid.uuid4().hex}")
    h.db.add(tenant)
    await h.db.flush()
    foreign = Tool(name=f"foreign-{uuid.uuid4().hex}", display_name="他企工具", tenant_id=tenant.id, enabled=True)
    h.db.add(foreign)
    await h.db.flush()
    catalog = await h.client.get("/api/employee-studio/catalog")
    assert catalog.status_code == 200
    assert str(foreign.id) not in {item["id"] for item in catalog.json()["tools"]}
    draft = await create_draft(h, tool_ids=[foreign.id])
    response = await h.client.post(
        "/api/agents/",
        json={
            "name": "不应创建的员工",
            "employee_blueprint_id": draft["id"],
            "employee_blueprint_revision": 1,
            "primary_model_id": str(h.model.id),
        },
    )
    assert response.status_code == 400
    h.setup.assert_not_awaited()


@pytest.mark.asyncio
async def test_creation_rejects_disabled_model_even_after_draft_check(harness):
    h = harness
    draft = await create_draft(h)
    assert (await h.client.post(f"/api/employee-studio/blueprints/{draft['id']}/check")).json()["ready"]
    h.model.enabled = False
    await h.db.flush()
    response = await h.client.post(
        "/api/agents/",
        json={
            "name": "测试员工",
            "employee_blueprint_id": draft["id"],
            "employee_blueprint_revision": 1,
            "primary_model_id": str(h.model.id),
        },
    )
    assert response.status_code == 400
    h.setup.assert_not_awaited()
