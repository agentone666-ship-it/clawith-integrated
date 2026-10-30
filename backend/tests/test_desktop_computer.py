"""Atomic-tool authority, live-before-completion and sampler cleanup."""

import asyncio
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from test_desktop_automation import OTHER, USER
from test_desktop_automation import fixture as fixture  # noqa: PLC0414 -- Pytest fixture re-export.

from app.models.agent_run import AgentRun
from app.models.user import User
from app.services.desktop_automation.computer import Computer, latest, router


class DB:
    def __init__(self, actor, binding=True):
        self.actor, self.binding = actor, binding

    async def get(self, cls, ident):
        if cls is User:
            return USER
        return self.actor if cls is AgentRun else SimpleNamespace(enabled=True)

    async def execute(self, query):
        return self

    def scalar_one_or_none(self):
        return uuid.uuid4() if self.binding else None

    def scalars(self):
        return self

    def all(self):
        return [self.actor.id]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def actor():
    return SimpleNamespace(
        id=uuid.uuid4(), agent_id=uuid.uuid4(), tenant_id=USER.tenant_id, origin_user_id=USER.id, lane_held=True
    )


@pytest.mark.parametrize("condition", ["valid", "unassigned", "ended", "foreign_agent", "foreign_tenant"])
async def test_actor_authority(fixture, condition):
    service, _, _ = fixture
    value = actor()
    db = DB(value, condition != "unassigned")
    meta = {"run_id": str(value.id), "agent_id": str(value.agent_id), "tenant_id": str(value.tenant_id)}
    if condition == "ended":
        value.lane_held = False
    if condition == "foreign_agent":
        meta["agent_id"] = str(uuid.uuid4())
    if condition == "foreign_tenant":
        meta["tenant_id"] = str(uuid.uuid4())
    computer = Computer(service)
    if condition == "valid":
        assert await computer.actor(db, meta) is value
    else:
        with pytest.raises(HTTPException):
            await computer.actor(db, meta)
    assert not service.driver.owners


async def test_frame_before_slow_action_private_and_sampler_stops(fixture, monkeypatch):
    service, _, _ = fixture
    value = actor()
    db = DB(value)
    computer = Computer(service)
    service.driver.runtime_contexts = {}
    entered, finish = asyncio.Event(), asyncio.Event()

    async def call(*args):
        entered.set()
        await finish.wait()
        return {"content": [{"type": "text", "text": "done"}]}

    monkeypatch.setattr(service.driver, "call", call, raising=False)
    monkeypatch.setattr("app.services.desktop_automation.computer.async_session", lambda: db)
    running = asyncio.create_task(
        computer.call(db, value, {"action": "click", "params": {}, "request_id": "live-test"})
    )
    await entered.wait()
    assert not running.done()
    image = await latest(service, db, USER, value.id)
    assert image["sequence"] and image["image"] and image["captured_at"]
    with pytest.raises(HTTPException):
        await latest(service, db, OTHER, value.id)
    finish.set()
    await running
    path = service.config.evidence_dir / "computer" / str(value.id) / "live.png"
    value.lane_held = False
    await asyncio.wait_for(computer.tasks[value.id], 2)
    version = path.stat().st_mtime_ns
    await asyncio.sleep(0.9)
    assert path.stat().st_mtime_ns == version and not service.driver.owners
    await computer.close()


async def test_transport_rejects_forged_identity_and_malformed_json(fixture):
    service, _, _ = fixture
    app = FastAPI()
    app.state.desktop_computer = Computer(service)
    app.include_router(router)
    token = service.tool_token(USER.tenant_id, uuid.UUID(service.config.driver_tool_id))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/automation-mcp/computer", json={})).status_code == 401
        for raw in ["{", "[]"]:
            response = await client.post(
                "/api/automation-mcp/computer", content=raw, headers={"Authorization": "Bearer " + token}
            )
            assert response.json()["result"]["isError"]
    assert not service.driver.owners


async def test_specific_computer_route_precedes_version_wildcard(fixture):
    from app.services.desktop_automation.application import app

    service, _, _ = fixture
    app.state.desktop_computer = Computer(service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/automation-mcp/computer", json={})
        assert response.status_code == 401
    assert not service.driver.owners
