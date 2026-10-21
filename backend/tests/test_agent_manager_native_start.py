"""Native Runtime readiness must not depend on the legacy gateway image."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import agent_manager as manager_module


def manager_and_agent(monkeypatch, *, enabled=True, agent_type="native", container_id=None, deleted_at=None):
    monkeypatch.setattr(manager_module, "settings", SimpleNamespace(
        AGENT_RUNTIME_V2_ENABLED=enabled, AGENT_RUNTIME_V2_AGENT_IDS="", AGENT_RUNTIME_V2_SOURCE_TYPES="",
    ))
    manager = object.__new__(manager_module.AgentManager)
    manager.docker_client = object()
    manager._materialize_agent_dir = AsyncMock(side_effect=RuntimeError("gateway path reached"))
    agent = SimpleNamespace(id=uuid.uuid4(), agent_type=agent_type, container_id=container_id,
                            deleted_at=deleted_at, status="creating", last_active_at=None)
    return manager, agent


@pytest.mark.asyncio
async def test_native_runtime_is_available_without_docker_image(monkeypatch):
    manager, agent = manager_and_agent(monkeypatch)
    assert await manager.start_container(None, agent) is None
    assert agent.status == "idle" and agent.last_active_at is not None
    assert agent.container_id is None
    manager._materialize_agent_dir.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [
    {"enabled": False}, {"agent_type": "openclaw"}, {"container_id": "existing-container"},
])
async def test_other_start_paths_still_reach_gateway_setup(monkeypatch, options):
    manager, agent = manager_and_agent(monkeypatch, **options)
    with pytest.raises(RuntimeError, match="gateway path reached"):
        await manager.start_container(None, agent)
    assert agent.status == "creating"
    manager._materialize_agent_dir.assert_awaited_once_with(agent.id)


@pytest.mark.asyncio
async def test_deleted_native_agent_cannot_become_available(monkeypatch):
    manager, agent = manager_and_agent(monkeypatch, deleted_at="deleted")
    assert await manager.start_container(None, agent) is None
    assert agent.status == "creating" and agent.last_active_at is None
    manager._materialize_agent_dir.assert_not_awaited()
