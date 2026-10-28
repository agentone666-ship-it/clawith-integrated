"""Read-only readiness projection for the human coding-Agent handoff guide."""

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_management_scope import manageable_agents
from app.models.agent import Agent
from app.models.tool import AgentTool
from app.models.user import User

from .registry import AutomationRegistry
from .service import fail


class AuthoringGuide:
    def __init__(self, registry: AutomationRegistry):
        self.registry = registry

    async def readiness(self, db: AsyncSession, user: User, search: str, offset: int) -> dict:
        if len(search) > 120 or not 0 <= offset <= 10000:
            fail(422, "Invalid search or offset")
        status = await self.registry.status(db, user)
        query = manageable_agents(user).where(Agent.agent_type == "native")
        if search.strip():
            query = query.where(Agent.name.contains(search.strip(), autoescape=True))
        total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        assigned = exists(
            select(AgentTool.id).where(
                AgentTool.agent_id == Agent.id,
                AgentTool.tool_id == self.registry.tool_id,
                AgentTool.enabled.is_(True),
            )
        )
        agents = (
            (await db.execute(query.order_by(assigned.desc(), Agent.name, Agent.id).offset(offset).limit(50)))
            .scalars()
            .all()
        )
        ids = [a.id for a in agents]
        enabled = (
            set(
                (
                    await db.execute(
                        select(AgentTool.agent_id).where(
                            AgentTool.agent_id.in_(ids),
                            AgentTool.tool_id == self.registry.tool_id,
                            AgentTool.enabled.is_(True),
                        )
                    )
                ).scalars()
            )
            if ids
            else set()
        )
        return {
            "manager": {k: status[k] for k in ("tool_id", "enabled", "name")},
            "items": [
                {
                    "id": str(a.id),
                    "name": a.name,
                    "assigned": a.id in enabled,
                    "ready": bool(status["enabled"] and a.id in enabled),
                }
                for a in agents
            ],
            "total": total,
            "offset": offset,
            "next_offset": offset + 50 if offset + len(agents) < total else None,
        }
