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
