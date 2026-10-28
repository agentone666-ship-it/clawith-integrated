"""Readiness must reflect current central grants without granting anything."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from test_automation_assignments import agent, prepare
from test_desktop_automation import OTHER, TENANT, USER
from test_desktop_automation import fixture as fixture  # noqa: PLC0414 -- Pytest fixture re-export.

from app.models.tool import AgentTool, Tool
from app.services.desktop_automation.authoring import AuthoringGuide
from app.services.desktop_automation.registry import AutomationRegistry, RegistryCall


async def test_readiness_requires_global_and_agent_enablement_without_mutation(fixture):
    service, sessions, _, _ = await prepare(fixture)
    registry = AutomationRegistry(service, fixture[1])
    guide = AuthoringGuide(registry)
    async with sessions() as db:
        a, b = agent("Ready"), agent("Disabled assignment")
        db.add_all([a, b])
        await db.commit()
        missing = await guide.readiness(db, USER, "", 0)
        assert missing["manager"]["tool_id"] is None
        assert missing["spec_markdown"].startswith("# 桌面自动化 Agent 工作规范")
        assert all(not x["ready"] for x in missing["items"])
        assert await db.get(Tool, registry.tool_id) is None
        tool = Tool(
            id=registry.tool_id,
            tenant_id=TENANT,
            name="automation_registry",
            display_name="桌面自动化管理",
            enabled=False,
        )
        db.add(tool)
        await db.flush()
        db.add_all(
            [
                AgentTool(agent_id=a.id, tool_id=tool.id, enabled=True, config={}),
                AgentTool(agent_id=b.id, tool_id=tool.id, enabled=False, config={}),
            ]
        )
        await db.commit()
        disabled = await guide.readiness(db, USER, "", 0)
        assert not any(x["ready"] for x in disabled["items"])
        assert next(x for x in disabled["items"] if x["id"] == str(a.id))["assigned"]
        tool.enabled = True
        await db.commit()
        enabled = await guide.readiness(db, USER, "", 0)
        assert {x["id"] for x in enabled["items"] if x["ready"]} == {str(a.id)}
        assert enabled["items"][0]["id"] == str(a.id)
        await db.commit()
        rows = (await db.execute(select(AgentTool))).scalars().all()
        assert len(rows) == 2 and {r.agent_id for r in rows if r.enabled} == {a.id}


async def test_search_scope_native_pagination_and_no_writes(fixture):
    service, sessions, _, _ = await prepare(fixture)
    guide = AuthoringGuide(AutomationRegistry(service, fixture[1]))
    async with sessions() as db:
        db.add_all(
            [agent(f"Managed {i:03}") for i in range(61)]
            + [
                agent("Foreign", tenant_id=uuid.uuid4()),
                agent("Private", creator_id=OTHER.id, access_mode="private"),
                agent("Only usable", creator_id=OTHER.id),
                agent("Remote", agent_type="openclaw"),
            ]
        )
        await db.commit()
        first, second = await guide.readiness(db, USER, "", 0), await guide.readiness(db, USER, "", 50)
        assert first["total"] == 61 and len(first["items"]) == 50 and first["next_offset"] == 50
        assert len(second["items"]) == 11 and second["next_offset"] is None
        assert (await guide.readiness(db, USER, "%", 0))["total"] == 0
        assert (await guide.readiness(db, USER, "Managed 002", 0))["total"] == 1
        assert not (await db.execute(select(AgentTool))).scalars().all()
        foreign = SimpleNamespace(**{**vars(USER), "tenant_id": uuid.uuid4()})
        with pytest.raises(HTTPException) as error:
            await guide.readiness(db, foreign, "", 0)
        assert error.value.status_code == 403


@pytest.mark.parametrize("search,offset", [("x" * 121, 0), ("", -1), ("", 10001)])
async def test_readiness_owner_validates_bounds(fixture, search, offset):
    service, sessions, _, _ = await prepare(fixture)
    async with sessions() as db:
        with pytest.raises(HTTPException) as error:
            await AuthoringGuide(AutomationRegistry(service, fixture[1])).readiness(db, USER, search, offset)
        assert error.value.status_code == 422


async def test_agent_sdk_and_human_download_share_actual_markdown(fixture, monkeypatch):
    service, engine, sessions = fixture
    registry = AutomationRegistry(service, engine)

    async def actor(db, meta):
        return USER, SimpleNamespace()

    monkeypatch.setattr(registry, "actor", actor)
    async with sessions() as db:
        result = await registry.invoke(db, {}, RegistryCall(operation="sdk"))
        status = await registry.status(db, USER)
        spec = result["sdk"]
        assert spec == status["sdk"]
        assert spec.startswith("# 桌面自动化 Agent 工作规范")
        assert "不要把选 Tool" in spec and "必须调用 `create" in spec
        assert "最多三轮" in spec and "成功试运行不能发布" in spec
        assert "只写草稿" in spec and "不伪造 Run 身份" in spec
        assert len(spec.encode()) < 16384
        assert not service.driver.inputs
