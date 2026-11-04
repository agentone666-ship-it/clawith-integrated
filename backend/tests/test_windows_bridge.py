"""Execute the shipped Windows adapter's real session admission boundary."""

import ast
import asyncio
import hashlib
import json
import re
import time
from pathlib import Path

import pytest

ASSET = Path(__file__).parents[1] / "app/services/desktop_automation/sandbox_host/windows_bridge.py.in"


@pytest.fixture
def bridge(tmp_path):
    state = tmp_path / "state"
    (state / "calls").mkdir(parents=True)
    (state / "closed").mkdir()
    (tmp_path / "out").mkdir()

    def local_path(value):
        return tmp_path / value.removeprefix("C:/Clawith/")

    namespace = {
        "asyncio": asyncio,
        "hashlib": hashlib,
        "json": json,
        "re": re,
        "time": time,
        "Path": local_path,
        "STATE": state,
        "READS": {"get_desktop_state"},
    }
    node = next(n for n in ast.parse(ASSET.read_text()).body if isinstance(n, ast.ClassDef) and n.name == "Driver")
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ASSET), "exec"), namespace)  # noqa: S102 -- Execute only the shipped adapter class, never caller/model source.
    driver = namespace["Driver"]()
    driver.tools = {
        "get_desktop_state": {"inputSchema": {"properties": {}}},
        "type_text": {"inputSchema": {"properties": {}}},
    }
    driver.owner = "record_authorized"
    driver.expires = time.monotonic() + 300
    return driver, state


async def test_authorized_read_renews_ended_native_session_without_changing_its_label(bridge):
    driver, _ = bridge
    calls = []

    async def request(method, params):
        calls.append(params)
        return {"result": {"content": [{"type": "image", "data": "aW1hZ2U="}]}}

    driver.request = request
    result = await driver.call({"action": "get_desktop_state", "params": {}, "session_id": "record_authorized"})
    assert result["content"][0]["type"] == "image"
    assert [c["name"] for c in calls] == ["start_session", "get_desktop_state"]
    assert {c["arguments"]["session"] for c in calls} == {"record_authorized"}


async def test_ended_native_write_is_returned_once_without_automatic_restart_or_replay(bridge):
    driver, _ = bridge
    calls = []

    async def request(method, params):
        calls.append(params)
        return {"result": {"isError": True, "content": [{"type": "text", "text": "session has ended"}]}}

    driver.request = request
    result = await driver.call(
        {
            "action": "type_text",
            "params": {"text": "fixture"},
            "session_id": "record_authorized",
            "request_id": "write_fixture",
        }
    )
    assert result["isError"]
    assert [c["name"] for c in calls] == ["type_text"]


async def test_released_manual_label_cannot_be_revived_by_a_read(bridge):
    driver, state = bridge
    (state / "closed" / "record_authorized").touch()
    calls = []

    async def request(*args):
        calls.append(args)
        return {"result": {}}

    driver.request = request
    with pytest.raises(ValueError, match="released"):
        await driver.call({"action": "get_desktop_state", "params": {}, "session_id": "record_authorized"})
    assert not calls


def test_bridge_upload_preserves_exact_asset_below_windows_command_line_limit(tmp_path, monkeypatch):
    import base64

    from app.services.desktop_automation.sandbox_host.provider import Libvirt

    p = Libvirt(tmp_path, tmp_path / "template")
    commands = []
    monkeypatch.setattr(p, "powershell", lambda ident, source: commands.append(source))
    p.upload_bridge("00000000-0000-0000-0000-000000000001")
    blocks = [base64.b64decode(re.search(r"FromBase64String\('([^']+)'\)", s)[1]) for s in commands]
    assert b"".join(blocks) == ASSET.read_bytes()
    assert max(len(base64.b64encode(s.encode("utf-16-le"))) + 200 for s in commands) < 32767


def planner():
    tree = ast.parse(ASSET.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "recording_events")
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ASSET), "exec"), namespace)  # noqa: S102 -- Shipped pure planner only.
    return namespace["recording_events"]


def test_manual_input_plan_handles_scaled_pixels_unicode_and_modifier_release():
    plan = planner()
    assert plan("click", {"x": 1279, "y": 799}, 1280, 800) == [("move", 65535, 65535), ("left", False), ("left", True)]
    assert len(plan("double_click", {"x": 0, "y": 0}, 1280, 800)) == 5
    assert plan("type_text", {"text": "中😀"}, 1280, 800) == [
        ("unicode", 0x4E2D, False),
        ("unicode", 0x4E2D, True),
        ("unicode", 0xD83D, False),
        ("unicode", 0xD83D, True),
        ("unicode", 0xDE00, False),
        ("unicode", 0xDE00, True),
    ]
    assert plan("hotkey", {"key": "r", "modifiers": ["win"]}, 1280, 800) == [
        ("key", 91, False),
        ("key", 82, False),
        ("key", 82, True),
        ("key", 91, True),
    ]
    assert plan("scroll", {"direction": "down", "amount": 3}, 1280, 800) == [("wheel", -360, False)]


@pytest.mark.parametrize(
    "action,params",
    [
        ("click", {"x": 1280, "y": 10}),
        ("click", {"x": -1, "y": 0}),
        ("click", {"x": float("nan"), "y": 1}),
        ("type_text", {"text": "x" * 8001}),
        ("hotkey", {"key": "a", "modifiers": ["unsafe"]}),
        ("scroll", {"direction": "down", "amount": 200}),
        ("launch_app", {}),
    ],
)
def test_invalid_manual_batches_fail_before_os_submission(action, params):
    with pytest.raises(ValueError, match="no action was dispatched"):
        planner()(action, params, 1280, 800)


async def test_manual_input_is_fenced_durable_and_not_available_to_agent_runs(bridge):
    driver, state = bridge
    native = []
    physical = []

    async def request(method, params):
        native.append(params)
        return {"result": {"content": []}}

    driver.request = request
    driver.call.__globals__["recording_input"] = lambda action, params: (
        physical.append((action, params.copy())) or {"content": [{"type": "text", "text": "submitted"}]}
    )
    denied = {
        "action": "type_text",
        "params": {"_recording_input": True, "text": "fixture"},
        "session_id": "run_" + "a" * 32,
        "request_id": "manual_fixture",
    }
    with pytest.raises(ValueError, match="authorized manual recording"):
        await driver.call(denied)
    assert not native and not physical and not list((state / "calls").iterdir())
    sid = "record_" + "b" * 32
    driver.owner = sid

    def allowed():
        return {
            "action": "type_text",
            "params": {"_recording_input": True, "text": "fixture"},
            "session_id": sid,
            "request_id": "manual_fixture",
        }

    first = await driver.call(allowed())
    second = await driver.call(allowed())
    assert first == second and len(physical) == 1 and not native
    assert "_recording_input" not in physical[0][1]


async def test_uncertain_physical_input_is_cached_without_replay(bridge):
    driver, _ = bridge
    sid = "record_" + "c" * 32
    driver.owner = sid
    attempts = []

    def physical(action, params):
        attempts.append(action)
        raise RuntimeError("Unknown desktop input outcome; inspect the screen")

    driver.call.__globals__["recording_input"] = physical

    def args():
        return {
            "action": "type_text",
            "params": {"_recording_input": True, "text": "fixture"},
            "session_id": sid,
            "request_id": "uncertain_fixture",
        }

    first = await driver.call(args())
    second = await driver.call(args())
    assert first["isError"] and second == first and attempts == ["type_text"]


async def test_recording_frame_uses_current_console_capture_without_native_snapshot_cache(bridge):
    driver, _ = bridge
    sid = "record_" + "d" * 32
    driver.owner = sid
    calls = []

    async def request(method, params):
        calls.append(params["name"])
        return {"result": {"content": []}}

    driver.request = request
    driver.call.__globals__["recording_desktop"] = lambda: {
        "content": [{"type": "image", "data": "fresh-pixels"}],
        "structuredContent": {"screenshot_width": 1280, "screenshot_height": 800},
    }
    result = await driver.call({"action": "get_desktop_state", "params": {}, "session_id": sid})
    assert calls == ["start_session"]
    assert result["content"][0]["data"] == "fresh-pixels"
    assert result["structuredContent"]["recording_protocol"] == 2


def test_native_launch_does_not_inject_remote_debugging_flags():
    source = ASSET.read_text()
    assert "business_browser_params" not in source
    assert "--remote-debugging-port=" not in source


async def test_business_navigation_requires_live_task_and_replays_only_confirmed_receipt(bridge):
    from types import SimpleNamespace

    driver, state = bridge
    calls = []

    async def call(method, params):
        calls.append((method, params))
        return {"targetId": "fixture"}

    driver.navigate_business.__func__.__globals__["browser"] = SimpleNamespace(lock=asyncio.Lock())

    async def navigate(urls):
        for url in urls:
            await call("Target.createTarget", {"url": url})

    driver.navigate_business.__func__.__globals__["business_browser"] = SimpleNamespace(navigate=navigate)
    receipt = state / "calls/record_authorized-browser_fixture.json"
    receipt.write_text(json.dumps({"browser_urls": ["https://business.example"]}))
    assert await driver.navigate_business("record_authorized", "browser_fixture") == {"ok": True}
    assert await driver.navigate_business("record_authorized", "browser_fixture") == {"ok": True}
    assert len(calls) == 1
    driver.owner = None
    with pytest.raises(ValueError, match="no longer active"):
        await driver.navigate_business("record_authorized", "browser_fixture")
    assert len(calls) == 1


async def test_uncertain_business_navigation_is_never_replayed(bridge):
    from types import SimpleNamespace

    driver, state = bridge
    calls = []

    async def call(method, params):
        calls.append(method)
        raise TimeoutError

    driver.navigate_business.__func__.__globals__["browser"] = SimpleNamespace(lock=asyncio.Lock())

    async def navigate(urls):
        for url in urls:
            await call("Target.createTarget", {"url": url})

    driver.navigate_business.__func__.__globals__["business_browser"] = SimpleNamespace(navigate=navigate)
    receipt = state / "calls/record_authorized-browser_fixture.json"
    receipt.write_text(json.dumps({"browser_urls": ["https://business.example"]}))
    with pytest.raises(TimeoutError):
        await driver.navigate_business("record_authorized", "browser_fixture")
    with pytest.raises(ValueError, match="unknown"):
        await driver.navigate_business("record_authorized", "browser_fixture")
    assert len(calls) == 1


async def test_native_request_deadline_includes_pipe_backpressure(bridge):
    driver, _ = bridge
    never = asyncio.Event()

    async def blocked_send(body):
        await never.wait()

    driver.send = blocked_send
    with pytest.raises(TimeoutError):
        await driver.request("ping", {}, timeout=0.02)
    assert not driver.pending


async def test_cancelled_navigation_releases_task_lock_and_fences_the_receipt(bridge):
    from types import SimpleNamespace

    driver, state = bridge
    browser_lock = asyncio.Lock()
    await browser_lock.acquire()
    driver.navigate_business.__func__.__globals__["browser"] = SimpleNamespace(lock=browser_lock)
    receipt = state / "calls/record_authorized-browser_fixture.json"
    receipt.write_text(json.dumps({"browser_urls": ["https://business.example"]}))
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.02):
            await driver.navigate_business("record_authorized", "browser_fixture")
    assert not driver.lock.locked()
    browser_lock.release()
    with pytest.raises(ValueError, match="unknown"):
        await driver.navigate_business("record_authorized", "browser_fixture")


async def test_release_without_native_input_never_touches_another_tasks_session(bridge):
    driver, state = bridge
    calls = []

    async def request(*args):
        calls.append(args)
        raise AssertionError("Foreign native session must not be touched")

    driver.request = request
    result = await driver.call({"action": "release", "params": {}, "session_id": "record_no_input"})
    assert not result.get("isError") and not calls
    assert driver.owner == "record_authorized"
    assert (state / "closed" / "record_no_input").exists()


async def test_release_requires_confirmed_native_success_and_remains_retryable(bridge):
    driver, state = bridge

    async def refused(*args):
        return {"result": {"isError": True}}

    driver.request = refused
    with pytest.raises(RuntimeError, match="unconfirmed"):
        await driver.call({"action": "release", "params": {}, "session_id": "record_authorized"})
    assert driver.owner == "record_authorized"
    assert not (state / "closed" / "record_authorized").exists()
    calls = []

    async def confirmed(method, params):
        calls.append(params)
        return {"result": {}}

    driver.request = confirmed
    await driver.call({"action": "release", "params": {}, "session_id": "record_authorized"})
    await driver.call({"action": "release", "params": {}, "session_id": "record_authorized"})
    assert driver.owner is None and (state / "closed" / "record_authorized").exists()
    assert [p["name"] for p in calls] == ["end_session"]


async def test_managed_browser_failure_is_safe_actionable_and_not_replayed(bridge):
    from types import SimpleNamespace

    driver, state = bridge
    driver.tools["launch_app"] = {"inputSchema": {"properties": {}}}
    calls = []

    async def failed_prepare(urls):
        calls.append(urls)
        raise RuntimeError("private-provider-detail")

    driver.call.__globals__["business_browser"] = SimpleNamespace(prepare=failed_prepare)
    args = {
        "action": "launch_app",
        "params": {"path": "msedge.exe"},
        "session_id": "record_authorized",
        "request_id": "launch_fixture",
    }
    first = await driver.call(args)
    second = await driver.call(args)
    assert first == second and first["isError"] and calls == [[]]
    assert "Business browser" in first["content"][0]["text"]
    assert "private-provider-detail" not in json.dumps(first)
    assert (state / "calls" / "record_authorized-launch_fixture.json").exists()
