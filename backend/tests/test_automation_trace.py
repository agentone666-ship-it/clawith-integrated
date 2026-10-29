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
