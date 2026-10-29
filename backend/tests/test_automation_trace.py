import uuid

import pytest
from fastapi import HTTPException
from test_desktop_automation import OTHER, USER, sample, workflow
from test_desktop_automation import fixture as fixture  # noqa: PLC0414

from app.services.desktop_automation.trace import capture, frame


async def test_sampling_and_whole_trace_bounds(fixture):
    service, _, _ = fixture
    ident = uuid.uuid4()
    result = {}
    for i in range(120):
        result = await capture(service, ident, "test", i, 120, sample().steps[0], result)
    assert len(result["trace"]) == 120
    assert sum(bool(x.get("frame")) for x in result["trace"]) == 30
    assert len(list((service.config.evidence_dir / str(ident)).glob("step-*.png"))) == 30
    capped = await capture(service, ident, "test", 0, 1, sample().steps[0], {"trace_bytes": 32 * 1024 * 1024})
    assert not capped["trace"][0].get("frame")


async def test_frame_readback_requires_workflow_authority_and_written_manifest(fixture):
    service, engine, sessions = fixture
    async with sessions() as db:
        w = await workflow(service, db)
        result = await engine.start(db, USER, w.id, {"order_id": "TRACE"}, "trace-image-test")
    await service.tasks[uuid.UUID(result["id"])]
    async with sessions() as db:
        value = await frame(engine, db, USER, uuid.UUID(result["id"]), 1)
        assert value["image"] and value["mime"] == "image/png"
        with pytest.raises(HTTPException):
            await frame(engine, db, OTHER, uuid.UUID(result["id"]), 1)
        with pytest.raises(HTTPException):
            await frame(engine, db, USER, uuid.UUID(result["id"]), -1)


@pytest.mark.parametrize(
    "message,uncertain",
    [("foreground_unavailable: no mouse input was sent", False), ("connection lost after delivery", True)],
)
async def test_driver_distinguishes_explicit_no_dispatch_from_unknown(fixture, monkeypatch, message, uncertain):
    import httpx

    from app.services.desktop_automation.driver import CuaDriver, DriverFailure

    service, _, _ = fixture
    client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"result": {"isError": True, "content": [{"type": "text", "text": message}]}}
        )
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=transport, **kw))
    with pytest.raises(DriverFailure) as error:
        await CuaDriver(service.config).call("test", "click", {}, "test-request")
    assert error.value.uncertain is uncertain


async def test_activity_is_scoped_to_latest_owned_session_run(fixture):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import JSON, Column, MetaData, Table
    from sqlalchemy.dialects.postgresql import JSONB

    from app.models.agent_run import AgentRun
    from app.models.agent_tool_execution import AgentToolExecution
    from app.services.desktop_automation.models import Playback
    from app.services.desktop_automation.trace import activity

    service, engine, sessions = fixture
    agent, session = uuid.uuid4(), uuid.uuid4()
    # Runtime JSONB defaults are PostgreSQL-specific. Use equivalent SQLite
    # storage columns; the production ORM queries and authorization stay real.
    async with sessions() as db:
        connection = await db.connection()
        metadata = MetaData()
        for model in (AgentRun, AgentToolExecution):
            Table(
                model.__tablename__,
                metadata,
                *[
                    Column(
                        c.name,
                        JSON() if isinstance(c.type, JSONB) else c.type,
                        primary_key=c.primary_key,
                        nullable=True,
                    )
                    for c in model.__table__.columns
                ],
            )
        await connection.run_sync(metadata.create_all)
        w = await workflow(service, db)
        when = datetime.now(UTC)

        def actor(offset, **overrides):
            values = {
                "id": uuid.uuid4(),
                "tenant_id": USER.tenant_id,
                "origin_user_id": USER.id,
                "agent_id": agent,
                "session_id": session,
                "source_type": "chat",
                "goal": "test",
                "run_kind": "foreground",
                "runtime_type": "legacy",
                "runtime_thread_id": "test",
                "graph_name": "test",
                "graph_version": "1",
                "model_turn_limit": 30,
                "delivery_status": "not_required",
                "lane_held": False,
                "created_at": when + timedelta(seconds=offset),
            }
            values.update(overrides)
            return AgentRun(**values)

        old, current = actor(0), actor(1)
        foreign = [
            actor(2, origin_user_id=OTHER.id),
            actor(3, session_id=uuid.uuid4()),
            actor(4, tenant_id=uuid.uuid4()),
            actor(5, agent_id=uuid.uuid4()),
        ]
        db.add_all([old, current, *foreign])
        await db.flush()
        previous = Playback(
            tenant_id=USER.tenant_id,
            owner_id=USER.id,
            workflow_id=w.id,
            agent_run_id=old.id,
            request_id="old-trial",
            digest="old",
            fingerprint="test",
            script=sample().model_dump(),
            status="failed",
            result={"error": "old failure"},
        )
        db.add(previous)
        await db.commit()
        value = await activity(engine, db, USER, agent, session)
        assert value["agent_run_id"] == str(current.id)
        assert value["tool_calls"] == 0 and value["playback"] is None
        assert await activity(engine, db, USER, agent, uuid.uuid4()) is None
        other_value = await activity(engine, db, OTHER, agent, session)
        assert other_value["agent_run_id"] == str(foreign[0].id)
        assert other_value["playback"] is None

        trial = Playback(
            tenant_id=USER.tenant_id,
            owner_id=USER.id,
            workflow_id=w.id,
            agent_run_id=current.id,
            request_id="current-trial",
            digest="new",
            fingerprint="test",
            script=sample().model_dump(),
            status="failed",
            result={"error": "Compiler rejected unsupported sleep"},
        )
        receipt = AgentToolExecution(
            tenant_id=USER.tenant_id,
            run_id=current.id,
            tool_call_id="call-1",
            tool_name="desktop_automation",
            status="failed",
            assistant_message_id="message-1",
            arguments_hash="test",
        )
        db.add_all([trial, receipt])
        await db.commit()
        value = await activity(engine, db, USER, agent, session)
        assert value["tool_calls"] == 1
        assert value["playback"]["id"] == str(trial.id)
        assert value["playback"]["result"]["error"] == "Compiler rejected unsupported sleep"


async def test_live_frame_is_readable_before_completion_without_observer_desktop_access(fixture):
    import asyncio

    from app.services.desktop_automation.live import latest_frame

    service, engine, sessions = fixture
    service.driver.block = asyncio.Event()
    async with sessions() as db:
        w = await workflow(service, db)
        value = await engine.start(db, USER, w.id, {"order_id": "LIVE"}, "live-before-completion")
    ident = uuid.UUID(value["id"])
    await service.driver.dispatched.wait()
    assert not service.tasks[ident].done()
    async with sessions() as db:
        before = list(service.driver.inputs)
        image = await latest_frame(engine, db, USER, ident)
        assert image["image"] and image["captured_at"] and image["sequence"]
        assert not service.tasks[ident].done()
        assert service.driver.inputs == before
        with pytest.raises(HTTPException):
            await latest_frame(engine, db, OTHER, ident)
    service.driver.block.set()
    await service.tasks[ident]
    path = service.config.evidence_dir / str(ident) / "live.png"
    version = path.stat().st_mtime_ns
    await asyncio.sleep(0.9)
    assert path.stat().st_mtime_ns == version
    assert not service.driver.owners
