"""Agent delivery stops at a verified draft; human confirmation binds exact code."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from test_desktop_automation import USER, workflow
from test_desktop_automation import fixture as fixture  # noqa: PLC0414 -- Pytest fixture re-export.

from app.services.desktop_automation.models import Version
from app.services.desktop_automation.registry import AutomationRegistry, RegistryCall


async def test_agent_publish_requests_confirmation_without_publishing(fixture, monkeypatch):
    service, engine, sessions = fixture
    registry = AutomationRegistry(service, engine)

    async def actor(db, meta):
        return USER, None

    monkeypatch.setattr(registry, "actor", actor)
    async with sessions() as db:
        w = await workflow(service, db)
        with pytest.raises(HTTPException):
            await registry.invoke(db, {}, RegistryCall(operation="publish", workflow_id=w.id))
        trial = await engine.start(db, USER, w.id, {"order_id": "CONFIRM"}, "confirmation-trial")
    await service.tasks[uuid.UUID(trial["id"])]
    async with sessions() as db:
        pending = await registry.invoke(db, {}, RegistryCall(operation="publish", workflow_id=w.id))
        assert pending["status"] == "awaiting_user_confirmation"
        assert (await db.execute(select(func.count()).select_from(Version))).scalar_one() == 0
        assert pending["digest"] == trial["digest"]
        published = await service.publish(db, USER, w.id, 0, "user confirmed", pending["digest"])
        await db.commit()
        repeated = await service.publish(db, USER, w.id, 0, "repeat click", pending["digest"])
        assert repeated == published
        assert (await db.execute(select(func.count()).select_from(Version))).scalar_one() == 1
        with pytest.raises(HTTPException):
            await service.publish(db, USER, w.id, 0, "wrong source", "f" * 64)
