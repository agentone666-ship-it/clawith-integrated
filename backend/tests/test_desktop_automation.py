"""Behavior boundaries for recording, immutable publication and Cua playback."""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.tool import Tool
from app.services.desktop_automation.contracts import Script, Step, Target, render
from app.services.desktop_automation.driver import DriverFailure
from app.services.desktop_automation.executor import PlaybackEngine
from app.services.desktop_automation.models import (
    AutomationBase,
    Recording,
    RecordingAction,
    Version,
    Workflow,
)
from app.services.desktop_automation.service import AutomationService
from app.services.desktop_automation.settings import Settings

TENANT = uuid.uuid4()
USER = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT, role="member", is_active=True)
OTHER = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT, role="member", is_active=True)
TARGET = Target(app="desk.exe", title="业务工作台")


class Desktop:
    def __init__(self):
        self.owners = set()
        self.inputs = []
        self.fail_input = False
        self.assert_failures = 0
        self.block = None
        self.dispatched = asyncio.Event()

    async def frame(self, session):
        self.owners.add(session)
        return {"image": "aW1hZ2U=", "mime": "image/png", "width": 1280, "height": 800}

    async def anchor(self, session, step):
        return step

    async def execute(self, session, step, inputs, request_id, applications):
        self.owners.add(session)
        if step.action == "assert_text":
            if not self.inputs:
                raise DriverFailure("Result is not present before input", condition_absent=True)
            if self.assert_failures:
                self.assert_failures -= 1
                raise DriverFailure("Result is still loading", condition_absent=True)
            return {}
        self.inputs.append((request_id, step.text, dict(inputs)))
        self.dispatched.set()
        if self.block:
            await self.block.wait()
        if self.fail_input:
            raise DriverFailure("Provider timed out after dispatch", uncertain=True)
        return {}

    async def release(self, session):
        self.owners.discard(session)

    @staticmethod
    def png(frame):
        return b"fake-image-evidence"


@pytest.fixture
async def fixture(tmp_path, monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", execution_options={"schema_translate_map": {"desktop_automation": None}}
    )
    async with engine.begin() as c:
        await c.run_sync(AutomationBase.metadata.create_all)
        await c.run_sync(lambda con: Tool.__table__.create(con))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    config = Settings(
        str(TENANT),
        "http://driver/mcp",
        "private",
        "http://service/api/automation-mcp",
        "signing-key",
        tmp_path,
        str(uuid.uuid4()),
    )
    service = AutomationService(config)
    service.driver = Desktop()

    async def idle(db, **kwargs):
        return None

    monkeypatch.setattr(service, "assert_desktop_idle", idle)
    monkeypatch.setattr("app.services.desktop_automation.executor.async_session", sessions)
    play = PlaybackEngine(service)
    yield service, play, sessions
    await play.close()
    await engine.dispose()


def sample(text="${order_id}"):
    return Script(
        steps=[
            Step(id="input", action="type_text", text=text, target=TARGET),
            Step(id="check", action="assert_text", text="保存成功", target=TARGET),
        ],
        parameters={"order_id": "订单号"} if "${order_id}" in text else {},
    )


async def workflow(service, db, script=None):
    w = Workflow(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        owner_id=USER.id,
        name="采购草稿",
        description="创建测试采购草稿",
        draft=(script or sample()).model_dump(),
    )
    db.add(w)
    await db.commit()
    return w


@pytest.mark.parametrize("action", ["execute_code", "shell", "eval", "drag_unchecked"])
def test_script_rejects_executable_operations(action):
    with pytest.raises(ValidationError):
        Step(id="bad", action=action)


def test_parameter_contract_and_literal_rendering():
    with pytest.raises(ValidationError):
        Script(steps=[Step(id="x", action="type_text", text="${missing}")])
    with pytest.raises(ValidationError):
        Script(parameters={"unused": "unused"})
    assert render("${text}", {"text": "'); shell('bad');"}) == "'); shell('bad');"
    with pytest.raises(ValueError):
        sample().validate_inputs({"other": "wrong"})


def test_complete_script_bounds():
    Script(steps=[Step(id=str(i), action="press_key", key="tab") for i in range(120)])
    with pytest.raises(ValidationError):
        Script(steps=[Step(id=str(i), action="press_key", key="tab") for i in range(121)])
    with pytest.raises(ValidationError):
        Script(steps=[Step(id=str(i), action="type_text", text="中" * 8000) for i in range(6)])


async def test_tenant_and_owner_denials_precede_mutation(fixture):
    service, _, sessions = fixture
    async with sessions() as db:
        w = await workflow(service, db)
        with pytest.raises(HTTPException) as owner:
            await service.edit(db, OTHER, w.id, 0, sample("changed"), w.name, "")
        assert owner.value.status_code == 404
        wrong = SimpleNamespace(**{**vars(USER), "tenant_id": uuid.uuid4()})
        with pytest.raises(HTTPException) as tenant:
            await service.start_recording(db, wrong, w.id, 0)
        assert tenant.value.status_code == 403
        assert service.driver.inputs == []
        await db.refresh(w)
        assert w.revision == 0


async def test_optimistic_edit_does_not_overwrite(fixture):
    service, _, sessions = fixture
    async with sessions() as db:
        w = await workflow(service, db)
        await service.edit(db, USER, w.id, 0, sample("first"), w.name, "")
        with pytest.raises(HTTPException):
            await service.edit(db, USER, w.id, 0, sample("second"), w.name, "")
        await db.refresh(w)
        assert w.draft["steps"][0]["text"] == "first"


async def test_recording_idempotency_and_secret_value_not_persisted(fixture):
    service, _, sessions = fixture
    async with sessions() as db:
        w = await workflow(service, db)
        record = await service.start_recording(db, USER, w.id, 0)
        rid = uuid.UUID(record["id"])
        step = Step(id="secret", action="type_text", text="private-password", target=TARGET)
        first = await service.record_action(db, USER, rid, "request_unique", step, "password", "登录密码", True)
        second = await service.record_action(db, USER, rid, "request_unique", step, "password", "登录密码", True)
        assert first["status"] == second["status"] == "recorded"
        assert len(service.driver.inputs) == 1
        with pytest.raises(HTTPException):
            await service.record_action(
                db, USER, rid, "request_unique", step.model_copy(update={"text": "changed"}), "password", "", True
            )
        stored = await db.get(Recording, rid)
        receipt = (await db.execute(select(RecordingAction))).scalar_one()
        assert "private-password" not in json.dumps(stored.script)
        assert "private-password" not in json.dumps(receipt.result)
        assert stored.script["steps"][0]["text"] == "${password}"
        await service.stop_recording(db, USER, rid)
        assert not service.driver.owners
        assert stored.status == "stopped"
        await db.refresh(w)
        assert w.draft["secret_parameters"] == ["password"]


async def test_unknown_recording_input_pauses_and_does_not_repeat(fixture):
    service, _, sessions = fixture
    service.driver.fail_input = True
    async with sessions() as db:
        w = await workflow(service, db)
        record = await service.start_recording(db, USER, w.id, 0)
        rid = uuid.UUID(record["id"])
        step = Step(id="uncertain", action="type_text", text="one write", target=TARGET)
        result = await service.record_action(db, USER, rid, "unique_unknown", step, "", "")
        assert result["status"] == "unknown"
        assert result["recording"]["paused"]
        await service.record_action(db, USER, rid, "unique_unknown", step, "", "")
        assert len(service.driver.inputs) == 1
        await service.stop_recording(db, USER, rid)
        assert not service.driver.owners


async def test_playback_dedupes_pins_script_and_releases_desktop(fixture):
    service, play, sessions = fixture
    service.driver.assert_failures = 1
    async with sessions() as db:
        w = await workflow(service, db)
        row = await play.start(db, USER, w.id, {"order_id": "P-001"}, "playback_unique")
        ident = uuid.UUID(row["id"])
        duplicate = await play.start(db, USER, w.id, {"order_id": "P-001"}, "playback_unique")
        assert duplicate["id"] == row["id"]
        await service.edit(db, USER, w.id, 0, sample("new draft"), w.name, "")
        task = service.tasks.get(ident)
        if task:
            await task
        r = await play.get(db, USER, ident)
        await db.refresh(r)
        assert r.status == "succeeded"
        assert r.script["steps"][0]["text"] == "${order_id}"
        assert len(service.driver.inputs) == 1
        assert r.result["release_confirmed"] and not service.driver.owners
        assert (service.config.evidence_dir / str(ident) / "final.png").read_bytes() == b"fake-image-evidence"


async def test_unknown_playback_does_not_repeat_write(fixture):
    service, play, sessions = fixture
    service.driver.fail_input = True
    service.driver.assert_failures = 1000
    async with sessions() as db:
        w = await workflow(service, db)
        row = await play.start(db, USER, w.id, {"order_id": "P-001"}, "failed_playback")
        ident = uuid.UUID(row["id"])
        if task := service.tasks.get(ident):
            await task
        db.expire_all()
        r = await play.get(db, USER, ident)
        assert r.status == "unknown" and r.result["failed_step"] == 1
        await play.start(db, USER, w.id, {"order_id": "P-001"}, "failed_playback")
        assert len(service.driver.inputs) == 1
        assert not service.driver.owners


async def test_cancel_observes_terminal_resource_release(fixture):
    service, play, sessions = fixture
    service.driver.block = asyncio.Event()
    async with sessions() as db:
        w = await workflow(service, db)
        row = await play.start(db, USER, w.id, {"order_id": "P-001"}, "cancel_playback")
        ident = uuid.UUID(row["id"])
        await service.driver.dispatched.wait()
        await play.cancel(db, USER, ident)
        service.driver.block.set()
        if task := service.tasks.get(ident):
            await task
        db.expire_all()
        r = await play.get(db, USER, ident)
        assert r.status == "cancelled"
        assert len(service.driver.inputs) == 1
        assert not service.driver.owners


async def test_publication_requires_exact_validated_digest(fixture):
    service, play, sessions = fixture
    async with sessions() as db:
        w = await workflow(service, db)
        with pytest.raises(HTTPException):
            await service.publish(db, USER, w.id, 0, "untested")
        result = await play.start(db, USER, w.id, {"order_id": "P-001"}, "publish_validation")
        if task := service.tasks.get(uuid.UUID(result["id"])):
            await task
        published = await service.publish(db, USER, w.id, 0, "verified")
        await db.commit()
        v = await db.get(Version, uuid.UUID(published["version_id"]))
        original = json.dumps(v.script, sort_keys=True)
        await service.edit(db, USER, w.id, 0, sample("changed"), w.name, "")
        with pytest.raises(HTTPException):
            await service.publish(db, USER, w.id, 1, "unverified change")
        assert json.dumps(v.script, sort_keys=True) == original
        assert Script.model_validate(v.script).digest() == v.digest


async def test_uncertain_write_reconciles_only_authored_postcondition(fixture):
    service, play, sessions = fixture
    service.driver.fail_input = True
    async with sessions() as db:
        w = await workflow(service, db)
        row = await play.start(db, USER, w.id, {"order_id": "P-002"}, "reconcile_unique")
        ident = uuid.UUID(row["id"])
        if task := service.tasks.get(ident):
            await task
        db.expire_all()
        r = await play.get(db, USER, ident)
        assert r.status == "succeeded"
        assert r.result["reconciled_input_steps"] == [{"step": 1, "verified_by": 2}]
        assert len(service.driver.inputs) == 1
        assert not service.driver.owners


async def test_evidence_storage_failure_still_releases_desktop(fixture, monkeypatch):
    service, play, sessions = fixture

    def broken(frame):
        raise OSError("disk full")

    monkeypatch.setattr(service.driver, "png", broken)
    async with sessions() as db:
        w = await workflow(service, db)
        row = await play.start(db, USER, w.id, {"order_id": "P-003"}, "evidence_failure")
        ident = uuid.UUID(row["id"])
        if task := service.tasks.get(ident):
            await task
        db.expire_all()
        r = await play.get(db, USER, ident)
        assert r.status == "unknown" and r.result["release_confirmed"]
        assert not service.driver.owners


async def test_explicit_verification_resumes_paused_recording(fixture):
    service, _, sessions = fixture
    async with sessions() as db:
        w = await workflow(service, db)
        r = await service.start_recording(db, USER, w.id, 0)
        ident = uuid.UUID(r["id"])
        service.driver.fail_input = True
        await service.record_action(
            db, USER, ident, "uncertain_write", Step(id="write", action="type_text", text="saved"), "", ""
        )
        service.driver.fail_input = False
        checked = await service.record_action(
            db,
            USER,
            ident,
            "explicit_check",
            Step(id="verify", action="assert_text", text="保存成功", target=TARGET),
            "",
            "",
        )
        assert not checked["recording"]["paused"]
        assert len(checked["recording"]["script"]["steps"]) == 2
        await service.stop_recording(db, USER, ident)


async def test_window_click_reads_its_own_image_before_foreground_input(fixture, monkeypatch):
    from app.services.desktop_automation.driver import CuaDriver

    service, _, _ = fixture
    driver = CuaDriver(service.config)
    calls = []

    async def windows(session):
        return [
            {
                "app_name": "desk.exe",
                "title": "业务工作台",
                "pid": 100,
                "window_id": 200,
                "bounds": {"x": 280, "y": 60, "width": 800, "height": 600},
            }
        ]

    async def frame(session):
        calls.append("read")
        return {}

    async def call(session, action, params, request_id=None):
        calls.append((action, params))
        if action == "get_window_state":
            return {"structuredContent": {"screenshot_width": 798, "screenshot_height": 598}}
        return {}

    monkeypatch.setattr(driver, "windows", windows)
    monkeypatch.setattr(driver, "frame", frame)
    monkeypatch.setattr(driver, "call", call)
    await driver.execute("session", Step(id="click", action="click", x=100, y=90, target=TARGET), {}, "input_once", {})
    assert calls == [
        ("get_window_state", {"pid": 100, "window_id": 200, "max_elements": 100}),
        ("click", {"pid": 100, "window_id": 200, "delivery_mode": "foreground", "x": 99, "y": 89}),
    ]


def test_operation_identifier_does_not_shadow_business_request_id():
    script = Script(
        steps=[Step(id="text", action="type_text", text="${request_id}")], parameters={"request_id": "采购申请编号"}
    )
    schema = script.input_schema()
    assert schema["properties"]["request_id"]["description"] == "采购申请编号"
    assert "_operation_id" in schema["required"]


async def test_failed_precondition_read_is_not_proof_of_absence(fixture, monkeypatch):
    service, play, sessions = fixture

    async def disconnected(session, step, inputs, request_id, applications):
        if step.action == "assert_text":
            raise DriverFailure("Desktop connection interrupted")
        service.driver.inputs.append(request_id)

    monkeypatch.setattr(service.driver, "execute", disconnected)
    async with sessions() as db:
        w = await workflow(service, db)
        row = await play.start(db, USER, w.id, {"order_id": "P-004"}, "unreadable_precondition")
        ident = uuid.UUID(row["id"])
        if task := service.tasks.get(ident):
            await task
        db.expire_all()
        r = await play.get(db, USER, ident)
        assert r.status == "failed"
        assert not service.driver.inputs
        assert not service.driver.owners
