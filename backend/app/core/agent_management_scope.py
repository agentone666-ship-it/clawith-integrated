"""Batched SQL companion to permissions.can_manage_agent; configuration scope only."""

from sqlalchemy import exists, false, func, or_, select

from app.models.agent import Agent, AgentPermission
from app.models.user import User


def manageable_agents(user: User):
    """Apply the human configuration policy without one permission query per Agent."""
    query = select(Agent).where(Agent.tenant_id == user.tenant_id, Agent.deleted_at.is_(None))
    if not user.is_active or not user.tenant_id:
        return query.where(false())
    mode = func.coalesce(Agent.access_mode, "company")
    grant = exists(
        select(AgentPermission.id).where(
            AgentPermission.agent_id == Agent.id,
            AgentPermission.scope_type == "user",
            AgentPermission.scope_id == user.id,
            AgentPermission.access_level == "manage",
        )
    )
    conditions = [Agent.creator_id == user.id, (mode == "custom") & grant]
    if user.role in {"org_admin", "platform_admin"}:
        conditions.append(mode != "private")
    return query.where(or_(*conditions))
