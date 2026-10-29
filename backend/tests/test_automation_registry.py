"""Source publication uses real studio boundaries; pure worker fixtures are not GUI proof."""

import json
import subprocess
import sys
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from test_desktop_automation import OTHER, USER
from test_desktop_automation import fixture as fixture  # noqa: PLC0414 -- Pytest fixture re-export.

from app.services.desktop_automation.code_contracts import CodePlan, PythonScript, load_script
from app.services.desktop_automation.models import Playback, Version
from app.services.desktop_automation.python_compiler import CompilationError, PythonCompiler
from app.services.desktop_automation.python_worker import WORKER_SOURCE
from app.services.desktop_automation.registry import AutomationRegistry, RegistryCall


def source(code=None):
    return PythonScript(
        format="clawith.python.v1",
        parameters={"quantity": "数量", "price": "单价"},
        source=code
        or """from automation import ui, inputs
from decimal import Decimal
w = ui.window('desk.exe', '业务工作台')
amount = str((Decimal(inputs['quantity'])*Decimal(inputs['price'])).quantize(Decimal('0.01')))
ui.type_text(amount, target=w)
ui.assert_text('保存成功', target=w)
""",
    )


def worker(script, inputs):
    p = subprocess.run(
        [sys.executable, "-I", "-c", WORKER_SOURCE],
        input=json.dumps({"source": script.source, "inputs": inputs, "secret_parameters": script.secret_parameters}),
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return json.loads(p.stdout)


async def compile_fixture(self, script, inputs):
    result = worker(script, {k: v for k, v in inputs.items() if k not in script.secret_parameters})
    if not result["ok"]:
        raise CompilationError(result["diagnostic"])
    plan = CodePlan.model_validate(result["plan"])
    plan.validate_source(script)
    return plan, {
        "compiler_fingerprint": "a" * 64,
        "execution_plan_digest": "b" * 64,
        "compiler_stdout": result["stdout"],
    }


def test_computation_loops_source_lines_and_literal_data():
    s = source("""from automation import ui, inputs
w=ui.window('desk.exe', 'title ${literal}')
for value in ['甲', '乙', '${untouched}']:
    ui.type_text(value, target=w)
ui.assert_text('保存成功',target=w)
""")
    result = worker(s, {})
    plan = CodePlan.model_validate(result["plan"])
    assert [x.text for x in plan.steps[:3]] == ["甲", "乙", "${untouched}"]
    assert plan.source_lines["py_0001"] == 4
    assert plan.steps[0].target.title == "title ${literal}"
    assert load_script(s.model_dump()).digest() == s.digest()


@pytest.mark.parametrize(
    "code,expected,line",
    [
        ("missing_name + 1", "NameError", 1),
        ("if True print(1)", "SyntaxError", 1),
        ("import os", "ValueError", None),
        ('from automation import inputs\nprint(inputs["password"])', "TypeError", 2),
    ],
)
def test_worker_diagnostics(code, expected, line):
    s = source(code).model_copy(update={"parameters": {"password": "密码"}, "secret_parameters": ["password"]})
    r = worker(s, {})
    assert not r["ok"] and r["diagnostic"]["code"] == expected
    if line:
        assert r["diagnostic"]["line"] == line


def test_secret_opaque_until_executor_and_plan_requires_verification():
    s = source(
        "from automation import ui,inputs\nw=ui.window('desk.exe','title')\nui.type_text(inputs['password'],target=w)\nui.assert_text('完成',target=w)"
    ).model_copy(update={"parameters": {"password": "密码"}, "secret_parameters": ["password"]})
    plan = CodePlan.model_validate(worker(s, {})["plan"])
    assert plan.secret_bindings == {"py_0001": "password"}
    assert "actual-secret" not in plan.model_dump_json()
    assert plan.execution_steps({"password": "actual-secret"})[0].text == "actual-secret"
    with pytest.raises(ValidationError, match="ui.assert_text"):
        CodePlan.model_validate({"steps": [plan.steps[0].model_dump()]})


def test_source_bounds_and_input_contract():
    s = source()
    assert s.input_schema()["required"] == ["quantity", "price", "_operation_id"]
    s.validate_inputs({"quantity": "2", "price": "5"})
    for values in ({"quantity": "1"}, {"quantity": "x" * 8001, "price": "1"}):
        with pytest.raises(ValueError):
            s.validate_inputs(values)
    with pytest.raises(ValidationError):
        s.model_copy(update={"source": "界" * 50000}).__class__.model_validate(
            {**s.model_dump(), "source": "界" * 50000}
        )
    with pytest.raises(ValidationError):
        load_script({"format": "unsupported"})


async def test_python_test_publish_and_source_edit_invalidates_proof(fixture, monkeypatch):
    service, engine, sessions = fixture
    monkeypatch.setattr(PythonCompiler, "compile", compile_fixture)
    async with sessions() as db:
        w = await service.create(db, USER, "计算采购金额", "隔离业务测试", source())
        ident = uuid.UUID(w["id"])
        await db.commit()
        with pytest.raises(HTTPException) as exc:
            await service.publish(db, USER, ident, 0, "未测不可发布")
        assert exc.value.status_code == 409
        r = await engine.start(db, USER, ident, {"quantity": "7", "price": "12.50"}, "python-test-0001")
    await service.tasks[uuid.UUID(r["id"])]
    async with sessions() as db:
        row = await engine.get(db, USER, uuid.UUID(r["id"]))
        assert row.status == "succeeded" and row.result["release_confirmed"]
        assert service.driver.inputs[0][1] == "87.50"
        assert "compiled_plan" not in service.run_view(row)["result"]
        pub = await service.publish(db, USER, ident, 0, "经过测试")
        await db.commit()
        v = await db.get(Version, uuid.UUID(pub["version_id"]))
        assert v.validation_run_id == row.id and v.compiler_fingerprint == "a" * 64
        changed = source(source().source + "\n# changed")
        await service.edit(db, USER, ident, 0, changed, "计算采购金额", "")
        await db.commit()
        with pytest.raises(HTTPException) as exc:
            await service.publish(db, USER, ident, 1, "不可沿用旧测试")
        assert exc.value.status_code == 409
        assert v.script == source().model_dump()
    assert service.driver.owners == set()


async def test_compile_failure_is_durable_no_desktop_and_repair(fixture, monkeypatch):
    service, engine, sessions = fixture
    monkeypatch.setattr(PythonCompiler, "compile", compile_fixture)
    async with sessions() as db:
        w = await service.create(db, USER, "失败反馈", "", source("unknown_value + 1"))
        r = await engine.start(db, USER, uuid.UUID(w["id"]), {"quantity": "2", "price": "3"}, "failed-code-0001")
        assert r["status"] == "failed" and r["result"]["diagnostic"]["line"] == 1
        assert r["result"]["desktop_started"] is False
        repeat = await engine.start(db, USER, uuid.UUID(w["id"]), {"quantity": "2", "price": "3"}, "failed-code-0001")
        assert repeat["id"] == r["id"]
        assert service.driver.inputs == [] and service.driver.owners == set()
        assert (await db.execute(select(Playback))).scalars().one().id == uuid.UUID(r["id"])
        with pytest.raises(HTTPException):
            await service.start_recording(db, USER, uuid.UUID(w["id"]), 0)
        with pytest.raises(HTTPException):
            await service.edit(db, OTHER, uuid.UUID(w["id"]), 0, source(), "Denied", "")


async def test_published_compiler_change_fails_before_desktop(fixture, monkeypatch):
    service, engine, sessions = fixture
    monkeypatch.setattr(PythonCompiler, "compile", compile_fixture)
    async with sessions() as db:
        w = await service.create(db, USER, "固定环境", "", source())
        ident = uuid.UUID(w["id"])
        r = await engine.start(db, USER, ident, {"quantity": "1", "price": "2"}, "pin-test-0001")
    await service.tasks[uuid.UUID(r["id"])]
    async with sessions() as db:
        pub = await service.publish(db, USER, ident, 0, "固定环境")
        await db.commit()

        async def changed(self, script, inputs):
            plan, meta = await compile_fixture(self, script, inputs)
            return plan, {**meta, "compiler_fingerprint": "c" * 64}

        monkeypatch.setattr(PythonCompiler, "compile", changed)
        before = len(service.driver.inputs)
        r = await engine.start(
            db, USER, ident, {"quantity": "1", "price": "2"}, "pin-exec-0001", uuid.UUID(pub["version_id"])
        )
        assert r["status"] == "failed" and r["result"]["diagnostic"]["code"] == "compiler_changed"
        assert len(service.driver.inputs) == before and service.driver.owners == set()


@pytest.mark.parametrize("operation", ["create", "launch"])
async def test_registry_missing_identity_and_member_registration_denied(fixture, operation):
    service, engine, sessions = fixture
    registry = AutomationRegistry(service, engine)
    async with sessions() as db:
        with pytest.raises(HTTPException) as exc:
            await registry.invoke(db, {}, RegistryCall(operation=operation, name="unauthorized", script=source()))
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException) as exc:
            await registry.register(db, USER)
        assert exc.value.status_code == 403


async def test_mcp_cannot_authorize_by_model_arguments(fixture, monkeypatch):
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI

    from app.models.tool import AgentTool, Tool
    from app.services.desktop_automation.registry_mcp import router

    service, engine, sessions = fixture
    registry = AutomationRegistry(service, engine)
    admin = SimpleNamespace(**{**vars(USER), "role": "org_admin"})
    async with sessions() as db:
        connection = await db.connection()
        await connection.run_sync(lambda c: AgentTool.__table__.create(c))
        await registry.register(db, admin)
        await db.commit()
    monkeypatch.setattr("app.services.desktop_automation.registry_mcp.async_session", sessions)
    app = FastAPI()
    app.state.automation_registry = registry
    app.include_router(router)
    headers = {"Authorization": "Bearer " + service.tool_token(USER.tenant_id, registry.tool_id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers
    ) as client:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "automation_registry", "arguments": {"operation": "sdk"}},
        }
        denied = await client.post("/api/automation-mcp/registry", json=payload)
        assert denied.status_code == 200 and denied.json()["result"]["isError"]
        assert "Runtime identity" in denied.json()["result"]["content"][0]["text"]
        payload["params"]["arguments"]["_meta"] = {"run_id": str(uuid.uuid4())}
        denied = await client.post("/api/automation-mcp/registry", json=payload)
        assert denied.json()["result"]["isError"]
        listed = await client.post(
            "/api/automation-mcp/registry", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        assert listed.json()["result"]["tools"][0]["name"] == "automation_registry"
        unauthorized = await client.post(
            "/api/automation-mcp/registry", headers={"Authorization": "Bearer invalid"}, json=payload
        )
        assert unauthorized.status_code == 401
        async with sessions() as db:
            tool = await db.get(Tool, registry.tool_id)
            tool.enabled = False
            await db.commit()
        disabled = await client.post("/api/automation-mcp/registry", json={"id": 3, "method": "tools/list"})
        assert disabled.status_code == 403


async def test_executor_enforces_assignment_for_alternate_runtime_caller(fixture, monkeypatch):
    from types import SimpleNamespace

    from test_desktop_automation import sample

    from app.models.agent_run import AgentRun
    from app.models.tool import AgentTool

    service, engine, sessions = fixture
    actor = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=USER.tenant_id, agent_id=uuid.uuid4(), lane_held=True, origin_user_id=USER.id
    )
    async with sessions() as db:
        connection = await db.connection()
        await connection.run_sync(lambda c: AgentTool.__table__.create(c))
        w = await service.create(db, USER, "Boundary check", "", sample())
        original = db.get

        async def get(cls, ident, **kwargs):
            return actor if cls is AgentRun else await original(cls, ident, **kwargs)

        monkeypatch.setattr(db, "get", get)
        with pytest.raises(HTTPException) as denied:
            await engine.start(
                db, USER, uuid.UUID(w["id"]), {"order_id": "PR-SYNTHETIC"}, "no-assignment-0001", agent_run_id=actor.id
            )
        assert denied.value.status_code == 403
        assert "assigned" in denied.value.detail
        assert service.driver.inputs == [] and service.driver.owners == set()


def test_management_schema_exposes_native_objects_without_refs():
    from app.services.desktop_automation.registry_schema import registry_schema

    schema = registry_schema()
    assert schema["properties"]["script"]["type"] == "object"
    assert schema["properties"]["inputs"]["type"] == "object"
    assert schema["properties"]["target"]["type"] == "object"
    assert "$ref" not in json.dumps(schema)
    assert "anyOf" not in json.dumps(schema)
    valid = RegistryCall(operation="create", name="new", script=source())
    assert isinstance(valid.script, PythonScript)
    with pytest.raises(ValidationError):
        RegistryCall.model_validate({"operation": "create", "script": json.dumps(source().model_dump())})


def test_script_errors_select_actual_format_and_omit_irrelevant_branch():
    with pytest.raises(ValidationError) as failure:
        RegistryCall.model_validate(
            {"operation": "update", "script": {**source().model_dump(), "workflow_id": str(uuid.uuid4())}}
        )
    errors = failure.value.errors(include_input=False)
    assert len(errors) == 1
    assert errors[0]["loc"] == ("script", "clawith.python.v1", "workflow_id")


def test_recording_scaffold_preserves_modal_targets_literal_params_and_steps():
    from app.services.desktop_automation.contracts import Script, Step, Target
    from app.services.desktop_automation.scaffold import python_template

    script = Script(
        steps=[
            Step(id="write", action="type_text", target=Target(app="powershell.exe", title="Main"), text="${order}"),
            Step(
                id="confirm",
                action="click",
                target=Target(app="powershell.exe", title="Confirm Purchase"),
                x=457,
                y=257,
            ),
            Step(
                id="check",
                action="assert_text",
                target=Target(app="powershell.exe", title="Main"),
                text="saved ${order}",
            ),
        ],
        parameters={"order": "单号"},
    )
    template = PythonScript.model_validate(python_template(script))
    plan = CodePlan.model_validate(worker(template, {"order": "PR-${literal}"})["plan"])
    assert [s.action for s in plan.steps] == [s.action for s in script.steps]
    assert plan.steps[1].target.title == "Confirm Purchase"
    assert (plan.steps[1].x, plan.steps[1].y) == (457, 257)
    assert plan.steps[2].text == "saved PR-${literal}"
    secret = script.model_copy(update={"secret_parameters": ["order"]})
    with pytest.raises(ValueError, match="Mixed secret"):
        python_template(secret)


def test_escape_recovery_without_target_is_supported():
    result = worker(
        source(
            "from automation import ui\nui.key('esc', target=None)\nw=ui.window('desk.exe','title')\nui.assert_text('结果',target=w)"
        ),
        {},
    )
    assert result["ok"] and result["plan"]["steps"][0]["key"] == "esc"


async def test_launch_uses_configured_application_and_releases_observer(fixture, monkeypatch):
    from types import SimpleNamespace

    service, engine, sessions = fixture
    registry = AutomationRegistry(service, engine)
    actor = SimpleNamespace(id=uuid.uuid4(), agent_id=uuid.uuid4(), tenant_id=USER.tenant_id)

    async def identity(db, meta):
        return USER, actor

    monkeypatch.setattr(registry, "actor", identity)
    service.applications = {"business-desk": {"label": "工作台", "path": "configured.exe"}}
    # Use a bounded empty Runtime registry for the active-observer identity query.
    from sqlalchemy import text

    async with sessions() as db:
        await db.execute(text("CREATE TABLE agent_runs (id UUID, tenant_id UUID, lane_held BOOLEAN)"))
        service.driver.runtime_contexts = {}

        async def windows(session):
            return []

        service.driver.windows = windows
        result = await registry.invoke(db, {}, RegistryCall(operation="launch", application_id="business-desk"))
        assert result["window_count"] == 0
        assert len(service.driver.inputs) == 1
        assert not service.driver.owners
        with pytest.raises(HTTPException) as error:
            await registry.invoke(db, {}, RegistryCall(operation="launch", application_id="arbitrary.exe"))
        assert error.value.status_code == 422
        assert len(service.driver.inputs) == 1

        async def busy(db, **kwargs):
            raise HTTPException(409, "Desktop occupied")

        monkeypatch.setattr(service, "assert_desktop_idle", busy)
        with pytest.raises(HTTPException) as error:
            await registry.invoke(db, {}, RegistryCall(operation="launch", application_id="business-desk"))
        assert error.value.status_code == 409
        assert len(service.driver.inputs) == 1

        async def idle(db, **kwargs):
            return None

        monkeypatch.setattr(service, "assert_desktop_idle", idle)
        service.driver.fail_input = True
        from app.services.desktop_automation.driver import DriverFailure

        with pytest.raises(DriverFailure):
            await registry.invoke(db, {}, RegistryCall(operation="launch", application_id="business-desk"))
        assert not service.driver.owners


@pytest.mark.parametrize("operation", ["observe", "launch"])
async def test_desktop_observation_mcp_separates_image_from_text_budget(fixture, monkeypatch, operation):
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI

    from app.services.desktop_automation.registry_mcp import router

    service, engine, sessions = fixture
    registry = AutomationRegistry(service, engine)
    admin = SimpleNamespace(**{**vars(USER), "role": "org_admin"})
    async with sessions() as db:
        await registry.register(db, admin)
        await db.commit()

    async def invoke(db, meta, args):
        return {"image": "aW1h" * 20000, "mime": "image/png", "window_count": 1}

    monkeypatch.setattr(registry, "invoke", invoke)
    monkeypatch.setattr("app.services.desktop_automation.registry_mcp.async_session", sessions)
    app = FastAPI()
    app.state.automation_registry = registry
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/automation-mcp/registry",
            headers={"Authorization": "Bearer " + service.tool_token(USER.tenant_id, registry.tool_id)},
            json={
                "id": 1,
                "method": "tools/call",
                "params": {"name": "automation_registry", "arguments": {"operation": operation}},
            },
        )
    result = response.json()["result"]
    assert result["isError"] is False
    assert result["content"][1]["type"] == "image"
    assert len(result["content"][1]["data"]) > 60000
    assert json.loads(result["content"][0]["text"]) == {"window_count": 1}


async def test_compiled_probe_is_diagnosed_before_desktop_claim(fixture, monkeypatch):
    from test_desktop_automation import TARGET, workflow

    from app.services.desktop_automation.contracts import Step

    service, play, sessions = fixture

    async def compile_probe(self, script, inputs):
        return CodePlan(
            steps=[Step(id="probe", action="assert_text", target=TARGET, text="__PROBE_STOP__")],
            source_lines={"probe": 12},
        ), {"compiler_fingerprint": "a" * 64}

    monkeypatch.setattr(PythonCompiler, "compile", compile_probe)
    async with sessions() as db:
        w = await workflow(service, db, source())
        value = await play.start(db, USER, w.id, {"quantity": "1", "price": "2"}, "python-reject-debug-stop")
    assert value["status"] == "failed"
    assert value["result"]["diagnostic"]["code"] == "invalid_probe_assertion"
    assert value["result"]["diagnostic"]["line"] == 12
    assert value["result"]["desktop_started"] is False
    assert not service.driver.inputs and not service.driver.owners
