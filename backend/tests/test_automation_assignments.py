"""Atomic multi-Agent allocation and central permission scope."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from test_desktop_automation import OTHER, TENANT, USER, sample, workflow
from test_desktop_automation import fixture as fixture  # noqa: PLC0414 -- Pytest fixture re-export.

from app.core.agent_management_scope import manageable_agents
from app.models.agent import Agent, AgentPermission
from app.models.tool import AgentTool, Tool
from app.services.desktop_automation.assignments import VersionAssignments
from app.services.desktop_automation.models import Version


async def prepare(fixture):
    service, _, sessions = fixture
    async with sessions() as db:
        connection = await db.connection()
        for table in [Agent.__table__, AgentPermission.__table__, AgentTool.__table__]:
            await connection.run_sync(lambda c, table=table: table.create(c))
        w = await workflow(service, db)
        versions = []
        for i in range(2):
            tool = Tool(id=uuid.uuid4(), name="alloc_" + uuid.uuid4().hex, display_name="Version", tenant_id=TENANT)
            v = Version(
                id=uuid.uuid4(),
                tenant_id=TENANT,
                workflow_id=w.id,
                number=i + 1,
                script=sample().model_dump(),
                digest=sample().digest(),
                tool_id=tool.id,
            )
            db.add_all([tool, v])
            versions.append(v)
        await db.commit()
    return service, sessions, w, versions


def agent(name, **kw):
    values = {
        "id": uuid.uuid4(),
        "name": name,
        "tenant_id": TENANT,
        "creator_id": USER.id,
        "agent_type": "native",
        "access_mode": "company",
    }
    values.update(kw)
    return Agent(**values)


async def test_bulk_switches_only_selected_preserves_other_tools_and_deduplicates(fixture):
    service, sessions, w, (v1, v2) = await prepare(fixture)
    async with sessions() as db:
        a, b, c = agent("A"), agent("B"), agent("Untouched")
        other = Tool(id=uuid.uuid4(), name="unrelated", display_name="Other", tenant_id=TENANT)
        db.add_all([a, b, c, other])
        await db.flush()
        db.add_all([AgentTool(agent_id=x.id, tool_id=v1.tool_id, enabled=True, config={}) for x in [a, b, c]])
        db.add(AgentTool(agent_id=a.id, tool_id=other.id, enabled=True, config={"keep": 1}))
        await db.commit()
        allocation = VersionAssignments(service)
        result = await allocation.assign(db, USER, w.id, v2.id, [a.id, b.id])
        await db.commit()
        assert result["assigned_count"] == result["changed_count"] == 2
        again = await allocation.assign(db, USER, w.id, v2.id, [a.id, b.id])
        await db.commit()
        assert again["unchanged_count"] == 2 and again["changed_count"] == 0
        rows = (await db.execute(select(AgentTool).execution_options(populate_existing=True))).scalars().all()
        state = {(r.agent_id, r.tool_id): r.enabled for r in rows}
        assert len(rows) == 6
        assert state[a.id, v2.tool_id] and state[b.id, v2.tool_id]
        assert not state[a.id, v1.tool_id] and not state[b.id, v1.tool_id]
        assert state[c.id, v1.tool_id] and state[a.id, other.id]
        assert next(r.config for r in rows if r.tool_id == other.id) == {"keep": 1}
        legacy = await service.bind(db, USER, w.id, v1.id, a.id)
        await db.commit()
        assert legacy["agent_id"] == str(a.id)
        rows = (await db.execute(select(AgentTool).execution_options(populate_existing=True))).scalars().all()
        state = {(r.agent_id, r.tool_id): r.enabled for r in rows}
        assert state[a.id, v1.tool_id] and not state[a.id, v2.tool_id] and state[b.id, v2.tool_id]


@pytest.mark.parametrize("denial", ["other_tenant", "other_owner", "private", "deleted", "openclaw", "missing"])
async def test_invalid_target_rejects_entire_batch_without_writes(fixture, denial):
    service, sessions, w, versions = await prepare(fixture)
    async with sessions() as db:
        good, bad = agent("Good"), agent("Bad")
        if denial == "other_tenant":
            bad.tenant_id = uuid.uuid4()
        if denial == "other_owner":
            bad.creator_id = OTHER.id
        if denial == "private":
            bad.creator_id = OTHER.id
            bad.access_mode = "private"
        if denial == "deleted":
            bad.deleted_at = datetime.now(UTC)
        if denial == "openclaw":
            bad.agent_type = "openclaw"
        db.add_all([good, bad])
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await VersionAssignments(service).assign(
                db, USER, w.id, versions[0].id, [good.id, uuid.uuid4() if denial == "missing" else bad.id]
            )
        assert error.value.status_code == 403
        assert not (await db.execute(select(AgentTool).execution_options(populate_existing=True))).scalars().all()


async def test_candidates_are_bounded_searchable_and_reflect_bindings(fixture):
    service, sessions, w, versions = await prepare(fixture)
    async with sessions() as db:
        agents = [agent(f"Managed {i:03}") for i in range(61)]
        db.add_all(
            agents
            + [agent("Private", creator_id=OTHER.id, access_mode="private"), agent("Remote", agent_type="openclaw")]
        )
        await db.flush()
        db.add(AgentTool(agent_id=agents[0].id, tool_id=versions[0].tool_id, enabled=True, config={}))
        await db.commit()
        allocation = VersionAssignments(service)
        first = await allocation.candidates(db, USER, w.id, versions[0].id, "", 0)
        second = await allocation.candidates(db, USER, w.id, versions[0].id, "", 50)
        assert first["total"] == 61 and len(first["items"]) == 50 and first["next_offset"] == 50
        assert len(second["items"]) == 11 and second["next_offset"] is None
        assert first["items"][0]["assigned"] and first["items"][0]["versions"][0]["number"] == 1
        other = await allocation.candidates(db, USER, w.id, versions[1].id, "Managed 000", 0)
        assert not other["items"][0]["assigned"] and other["items"][0]["versions"][0]["number"] == 1
        assert (await allocation.candidates(db, USER, w.id, versions[0].id, "%", 0))["total"] == 0
        assert len((await db.execute(select(AgentTool).execution_options(populate_existing=True))).scalars().all()) == 1


async def test_scope_honors_custom_manage_private_and_inactive(fixture, monkeypatch):
    _, sessions, _, _ = await prepare(fixture)
    async with sessions() as db:
        custom = agent("Custom", creator_id=OTHER.id, access_mode="custom")
        use = agent("Use", creator_id=OTHER.id, access_mode="custom")
        private = agent("Private", creator_id=OTHER.id, access_mode="private")
        company = agent("Company", creator_id=OTHER.id)
        owned = agent("Owned", access_mode="private")
        db.add_all([custom, use, private, company, owned])
        await db.flush()
        db.add_all(
            [
                AgentPermission(agent_id=a.id, scope_type="user", scope_id=USER.id, access_level=l)
                for a, l in [(custom, "manage"), (use, "use")]
            ]
        )
        await db.commit()
        assert {a.id for a in (await db.execute(manageable_agents(USER))).scalars()} == {custom.id, owned.id}
        admin = SimpleNamespace(**{**vars(USER), "role": "org_admin"})
        assert {a.id for a in (await db.execute(manageable_agents(admin))).scalars()} == {
            custom.id,
            use.id,
            company.id,
            owned.id,
        }
        inactive = SimpleNamespace(**{**vars(USER), "is_active": False})
        assert not (await db.execute(manageable_agents(inactive))).scalars().all()
        # Query selection must agree with the existing configuration policy.
        from app.core.permissions import can_manage_agent

        async def permission(agent_id, user_id):
            return (
                await db.execute(
                    select(AgentPermission).where(
                        AgentPermission.agent_id == agent_id,
                        AgentPermission.scope_type == "user",
                        AgentPermission.scope_id == user_id,
                    )
                )
            ).scalar_one_or_none()

        from app.dao.agent_dao import agent_dao

        monkeypatch.setattr(agent_dao, "get_user_permission", permission)
        for caller in [USER, admin, inactive]:
            allowed = {a.id for a in (await db.execute(manageable_agents(caller))).scalars()}
            for target in [custom, use, private, company, owned]:
                assert bool(await can_manage_agent(caller, target)) == (target.id in allowed)


@pytest.mark.parametrize("kind", ["empty", "duplicate", "too_many"])
async def test_limits_enforced_at_mutation_boundary(fixture, kind):
    service, sessions, w, versions = await prepare(fixture)
    ids = [] if kind == "empty" else [uuid.uuid4() for _ in range(101)]
    if kind == "duplicate":
        ids = [versions[0].id] * 2
    async with sessions() as db:
        with pytest.raises(HTTPException) as error:
            await VersionAssignments(service).assign(db, USER, w.id, versions[0].id, ids)
        assert error.value.status_code == 422
        assert not (await db.execute(select(AgentTool).execution_options(populate_existing=True))).scalars().all()
