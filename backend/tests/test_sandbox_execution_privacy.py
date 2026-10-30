"""Sharing workflow source or admin privileges never shares execution data."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from test_desktop_automation import OTHER, USER, workflow
from test_desktop_automation import fixture as fixture  # noqa: PLC0414 -- Pytest fixture re-export.

from app.services.desktop_automation.models import Playback


async def test_workflow_creator_and_admin_cannot_read_other_accounts_execution(fixture):
    service, engine, sessions = fixture
    admin = SimpleNamespace(**{**vars(USER), "role": "org_admin"})
    async with sessions() as db:
        w = await workflow(service, db)
        record = Playback(
            id=uuid.uuid4(),
            tenant_id=USER.tenant_id,
            owner_id=OTHER.id,
            workflow_id=w.id,
            request_id="other_account_private_result",
            fingerprint="x" * 64,
            status="succeeded",
            script=w.draft,
            digest="x" * 64,
            input_summary={"private": "belongs to another account"},
            result={"private": "account result"},
        )
        db.add(record)
        await db.commit()
        detail = await service.detail(db, admin, w.id)
        assert not detail["runs"]
        with pytest.raises(HTTPException) as denied:
            await engine.get(db, admin, record.id)
        assert denied.value.status_code == 404
        own = await engine.get(db, OTHER, record.id)
        assert own.owner_id == OTHER.id
