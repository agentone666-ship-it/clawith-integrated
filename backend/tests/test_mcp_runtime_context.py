from contextlib import asynccontextmanager
from types import SimpleNamespace
import uuid

import pytest

from app.services import agent_tools
from app.services.mcp_client import MCPClient
from app.services.sandbox.run_scope import sandbox_run_scope_id


@pytest.mark.asyncio
@pytest.mark.parametrize("meta", [None, {"io.clawith/runtime": {"run_id": "trusted"}}])
async def test_metadata_is_outside_model_arguments(monkeypatch, meta):
    client = MCPClient("http://example.test/mcp", request_meta=meta)
    captured = []

    async def request(method, params):
        captured.append((method, params))
        return {"result": {"content": []}}

    monkeypatch.setattr(client, "_detect_and_request", request)
    arguments = {"action": "list_apps", "session_id": "model-changes-this"}
    await client.call_tool_result("computer", arguments)
    assert captured[0][1]["arguments"] == arguments
    assert captured[0][1].get("_meta") == meta
    assert ("_meta" in captured[0][1]) == (meta is not None)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "missing_run", "too_many", "missing_scope"])
async def test_runtime_metadata_uses_bounded_authoritative_run_facts(monkeypatch, case):
    rid, aid, tenant = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    held = [rid, uuid.uuid4()] if case != "too_many" else [uuid.uuid4() for _ in range(257)]
    run = None if case == "missing_run" else SimpleNamespace(tenant_id=tenant)
    statements = []

    class DB:
        async def execute(self, statement):
            statements.append(statement)
            if len(statements) == 1:
                return SimpleNamespace(scalar_one_or_none=lambda: run)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: held))

    @asynccontextmanager
    async def session():
        yield DB()

    monkeypatch.setattr(agent_tools, "async_session", session)
    token = sandbox_run_scope_id.set("" if case == "missing_scope" else str(rid))
    try:
        if case != "valid":
            with pytest.raises(ValueError):
                await agent_tools._mcp_runtime_request_meta(aid)
            return
        result = (await agent_tools._mcp_runtime_request_meta(aid))["io.clawith/runtime"]
    finally:
        sandbox_run_scope_id.reset(token)
    assert result == {"run_id": str(rid), "agent_id": str(aid), "tenant_id": str(tenant),
                      "active_run_ids": sorted(map(str, held))}
    assert "agent_runs.agent_id" in str(statements[0])
    assert "agent_runs.tenant_id" in str(statements[1])
    assert "agent_runs.lane_held IS true" in str(statements[1])


@pytest.mark.asyncio
async def test_opted_in_tool_does_not_dispatch_without_runtime_identity(monkeypatch):
    token = sandbox_run_scope_id.set("")
    try:
        result = await agent_tools._execute_resolved_mcp_target_outcome(
            {"full_name": "mcp_cua_computer", "raw_name": "computer",
             "server_url": "http://must-not-contact.invalid/mcp",
             "config": {"runtime_context_meta": True}}, {"action": "click"}, agent_id=uuid.uuid4(),
        )
    finally:
        sandbox_run_scope_id.reset(token)
    assert result.status == "failed"
    assert result.error_code == "mcp_runtime_context_unavailable"
