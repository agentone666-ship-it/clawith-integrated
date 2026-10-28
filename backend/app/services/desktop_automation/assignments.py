"""Optional post-publication allocation of a fixed Tool version to many Agents."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_management_scope import manageable_agents
from app.models.agent import Agent
from app.models.tool import AgentTool, Tool
from app.models.user import User

from .models import Version
from .service import AutomationService, fail


class VersionAssignments:
    def __init__(self, service: AutomationService):
        self.service = service

    async def _version(self, db, user, workflow_id, version_id):
        version = await self.service.version(db, user, workflow_id, version_id)
        tool = await db.get(Tool, version.tool_id) if version.tool_id else None
        if tool is None or tool.tenant_id != user.tenant_id or not tool.enabled:
            fail(409, "Published Tool is unavailable or disabled")
        return version

    async def candidates(
        self, db: AsyncSession, user: User, workflow_id: uuid.UUID, version_id: uuid.UUID, search: str, offset: int
    ) -> dict:
        version = await self._version(db, user, workflow_id, version_id)
        query = manageable_agents(user).where(Agent.agent_type == "native")
        if search:
            query = query.where(Agent.name.contains(search, autoescape=True))
        total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        agents = (await db.execute(query.order_by(Agent.name, Agent.id).offset(offset).limit(50))).scalars().all()
        ids = [a.id for a in agents]
        bindings = (
            (
                await db.execute(
                    select(AgentTool.agent_id, Version.id, Version.number)
                    .join(Version, Version.tool_id == AgentTool.tool_id)
                    .where(
                        AgentTool.agent_id.in_(ids),
                        AgentTool.enabled.is_(True),
                        Version.workflow_id == workflow_id,
                        Version.tenant_id == user.tenant_id,
                    )
                    .order_by(Version.number)
                )
            ).all()
            if ids
            else []
        )
        by_agent: dict = {}
        for agent_id, ident, number in bindings:
            by_agent.setdefault(agent_id, []).append({"id": str(ident), "number": number})
        return {
            "items": [
                {
                    "id": str(a.id),
                    "name": a.name,
                    "assigned": any(v["id"] == str(version.id) for v in by_agent.get(a.id, [])),
                    "versions": by_agent.get(a.id, []),
                }
                for a in agents
            ],
            "total": total,
            "offset": offset,
            "next_offset": offset + 50 if offset + len(agents) < total else None,
        }

    async def assign(
        self, db: AsyncSession, user: User, workflow_id: uuid.UUID, version_id: uuid.UUID, agent_ids: list[uuid.UUID]
    ) -> dict:
        # Both HTTP and the legacy/model caller enter the same authorization and
        # mutation boundary. Validate the whole selection before writing anything.
        if not 1 <= len(agent_ids) <= 100 or len(set(agent_ids)) != len(agent_ids):
            fail(422, "Select 1 to 100 distinct Agents")
        version = await self._version(db, user, workflow_id, version_id)
        agents = (
            (
                await db.execute(
                    manageable_agents(user)
                    .where(Agent.id.in_(agent_ids), Agent.agent_type == "native")
                    .order_by(Agent.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        if len(agents) != len(agent_ids):
            fail(
                403,
                "Selection includes unavailable Agents or Agents you cannot configure. No assignments were changed.",
            )
        related = select(Version.tool_id).where(Version.workflow_id == workflow_id, Version.tenant_id == user.tenant_id)
        existing = (
            (
                await db.execute(
                    select(AgentTool).where(AgentTool.agent_id.in_(agent_ids), AgentTool.tool_id == version.tool_id)
                )
            )
            .scalars()
            .all()
        )
        unchanged = len({b.agent_id for b in existing if b.enabled})
        await db.execute(
            update(AgentTool)
            .where(AgentTool.agent_id.in_(agent_ids), AgentTool.tool_id.in_(related))
            .values(enabled=False)
        )
        await db.execute(
            update(AgentTool)
            .where(AgentTool.agent_id.in_(agent_ids), AgentTool.tool_id == version.tool_id)
            .values(enabled=True)
        )
        found = {b.agent_id for b in existing}
        db.add_all(
            [
                AgentTool(agent_id=a.id, tool_id=version.tool_id, enabled=True, config={}, source="user_installed")
                for a in agents
                if a.id not in found
            ]
        )
        await db.flush()
        return {
            "version_id": str(version.id),
            "tool_id": str(version.tool_id),
            "number": version.number,
            "assigned_count": len(agents),
            "changed_count": len(agents) - unchanged,
            "unchanged_count": unchanged,
            "agents": [{"id": str(a.id), "name": a.name} for a in agents],
        }
