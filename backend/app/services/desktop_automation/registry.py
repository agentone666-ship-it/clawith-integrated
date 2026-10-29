"""Agent-authored source registry, sharing the manual studio lifecycle and policy."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.tool import AgentTool, Tool
from app.models.user import User
from app.services.tool_config import encrypt_sensitive_fields

from .code_contracts import ManagedScript
from .contracts import Script, Step, Target
from .driver import DriverFailure, result_text
from .executor import PlaybackEngine
from .registry_schema import registry_schema
from .scaffold import python_template
from .service import AutomationService, fail

SDK = Path(__file__).with_name("AUTOMATION_AGENT.md").read_text(encoding="utf-8")


class RegistryCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal[
        "sdk",
        "list",
        "get",
        "version",
        "observe",
        "launch",
        "create",
        "update",
        "test",
        "run_status",
        "publish",
        "bind",
        "execute",
    ]
    workflow_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=1000)
    script: ManagedScript | None = None
    revision: int = Field(default=0, ge=0)
    note: str = Field(default="", max_length=500)
    inputs: dict[str, str] = Field(default_factory=dict, max_length=40)
    request_id: str = Field(default="", max_length=80, pattern=r"^[a-zA-Z0-9_-]*$")
    offset: int = Field(default=0, ge=0, le=10000)
    source_offset: int = Field(default=0, ge=0, le=131072)
    target: Target | None = None
    application_id: str = Field(default="", max_length=80)


class AutomationRegistry:
    def __init__(self, service: AutomationService, engine: PlaybackEngine):
        self.service, self.engine = service, engine

    @property
    def tool_id(self) -> uuid.UUID:
        return uuid.uuid5(uuid.UUID(self.service.config.tenant_id), "desktop-automation-registry")

    async def status(self, db: AsyncSession, user: User) -> dict:
        self.service.authorize(user)
        tool = await db.get(Tool, self.tool_id)
        return {
            "tool_id": str(self.tool_id) if tool else None,
            "enabled": bool(tool and tool.enabled),
            "name": "automation_registry",
            "sdk": SDK,
        }

    async def register(self, db: AsyncSession, user: User) -> dict:
        tenant = self.service.authorize(user)
        if user.role not in {"org_admin", "platform_admin"}:
            fail(403, "An administrator must enable the automation management Tool")
        tool = await db.get(Tool, self.tool_id)
        if tool is None:
            db.add(
                Tool(
                    id=self.tool_id,
                    tenant_id=tenant,
                    name="automation_registry",
                    display_name="桌面自动化管理",
                    description="编写和管理桌面自动化：先 sdk/observe/get，创建或修改 Python/RPA 草稿，test 后按明确错误修复，成功才能 publish。bind 将固定版本 Tool 分配给业务 Agent。只能操作当前任务发起人有权限的流程和 Agent。",
                    type="mcp",
                    category="custom",
                    parameters_schema=registry_schema(),
                    mcp_server_url=self.service.config.public_mcp_url.rstrip("/") + "/registry",
                    mcp_server_name="Clawith automation registry",
                    mcp_tool_name="automation_registry",
                    enabled=True,
                    is_default=False,
                    source="admin",
                    config=encrypt_sensitive_fields(
                        {"api_key": self.service.tool_token(tenant, self.tool_id), "runtime_context_meta": True}
                    ),
                )
            )
        else:
            tool.enabled = True
            tool.parameters_schema = registry_schema()
        await db.flush()
        return await self.status(db, user)

    async def bind_manager(self, db: AsyncSession, user: User, agent_id: uuid.UUID) -> dict:
        from app.core.permissions import can_manage_agent
        from app.models.agent import Agent

        self.service.authorize(user)
        if user.role not in {"org_admin", "platform_admin"}:
            fail(403, "An administrator must assign the automation management Tool")
        tool, agent = await db.get(Tool, self.tool_id), await db.get(Agent, agent_id)
        if not tool or not tool.enabled:
            fail(409, "Enable the management Tool first")
        if agent is None or agent.tenant_id != user.tenant_id or not await can_manage_agent(db, user, agent):
            fail(403, "You cannot configure this Agent")
        row = (
            await db.execute(select(AgentTool).where(AgentTool.agent_id == agent_id, AgentTool.tool_id == tool.id))
        ).scalar_one_or_none()
        if row:
            row.enabled = True
        else:
            db.add(AgentTool(agent_id=agent_id, tool_id=tool.id, enabled=True, config={}, source="user_installed"))
        return {"agent_id": str(agent_id), "tool_id": str(tool.id)}

    async def actor(self, db: AsyncSession, meta: dict) -> tuple[User, AgentRun]:
        try:
            run_id, agent_id, tenant = (uuid.UUID(meta[k]) for k in ("run_id", "agent_id", "tenant_id"))
        except (ValueError, KeyError, TypeError, AttributeError):
            fail(403, "A genuine active Clawith Runtime identity is required")
        run = await db.get(AgentRun, run_id)
        tool = await db.get(Tool, self.tool_id)
        binding = (
            await db.execute(
                select(AgentTool.id)
                .where(AgentTool.agent_id == agent_id, AgentTool.tool_id == self.tool_id, AgentTool.enabled.is_(True))
                .limit(1)
            )
        ).scalar_one_or_none()
        if (
            not run
            or not run.lane_held
            or run.agent_id != agent_id
            or run.tenant_id != tenant
            or str(tenant) != self.service.config.tenant_id
            or not tool
            or not tool.enabled
            or not binding
        ):
            fail(403, "The active Agent Run must have the management Tool assigned")
        user = await db.get(User, run.origin_user_id) if run.origin_user_id else None
        if not user or user.tenant_id != tenant:
            fail(403, "This management operation needs an authenticated task origin user")
        self.service.authorize(user)
        return user, run

    async def invoke(self, db: AsyncSession, meta: dict, args: RegistryCall) -> dict:
        user, actor = await self.actor(db, meta)
        s, op = self.service, args.operation
        if op == "sdk":
            return {"sdk": SDK, "applications": [{"id": k, "label": v["label"]} for k, v in s.applications.items()]}
        if op == "list":
            rows = await s.list_workflows(db, user, args.offset)
            return {
                "items": rows[:10],
                "offset": args.offset,
                "next_offset": args.offset + 10 if len(rows) > 10 else None,
            }
        if op in {"observe", "launch"}:
            if op == "launch" and args.application_id not in s.applications:
                fail(422, "Choose an application_id returned by sdk; arbitrary executables are not allowed")
            return await self.observe(db, actor, args.target, args.application_id if op == "launch" else None)
        if op == "run_status":
            if not args.run_id:
                fail(422, "run_id is required")
            return s.run_view(await self.engine.get(db, user, args.run_id))
        if op == "create":
            if not args.name.strip() or args.script is None:
                fail(422, "create requires name and script")
            value = await s.create(db, user, args.name, args.description, args.script)
            return {
                "workflow_id": value["id"],
                "revision": value["revision"],
                "next": "test with inputs before publish",
            }
        if args.workflow_id is None:
            fail(422, "workflow_id is required")
        if op in {"get", "version"}:
            if op == "version":
                if args.version_id is None:
                    fail(422, "version_id is required")
                v = await s.version(db, user, args.workflow_id, args.version_id)
                value = {"id": str(v.id), "number": v.number, "digest": v.digest, "draft": v.script}
            else:
                value = await s.detail(db, user, args.workflow_id)
                value["runs"] = [{k: r[k] for k in ("id", "status", "progress", "digest")} for r in value["runs"][:5]]
                value["versions"] = value["versions"][:10]
            script = dict(value.pop("draft"))
            source = script.pop("source", None)
            steps = script.pop("steps", None)
            if source is not None:
                value.update(
                    source=source[args.source_offset : args.source_offset + 6000],
                    source_length=len(source),
                    next_source_offset=args.source_offset + 6000 if len(source) > args.source_offset + 6000 else None,
                )
            if steps is not None:
                try:
                    value["python_template"] = python_template(Script.model_validate({**script, "steps": steps}))
                except ValueError as exc:
                    value["python_template_omitted"] = str(exc)[:300]
                # RPA source is paged as steps to avoid oversized model context.
                value.update(
                    steps=steps[args.offset : args.offset + 20],
                    next_offset=args.offset + 20 if len(steps) > args.offset + 20 else None,
                )
            return {**value, "script": script}
        if op == "update":
            if args.script is None or not args.name.strip():
                fail(422, "update requires script and name")
            value = await s.edit(db, user, args.workflow_id, args.revision, args.script, args.name, args.description)
            return {"workflow_id": value["id"], "revision": value["revision"], "next": "test this revision"}
        if op == "publish":
            return await s.publish(db, user, args.workflow_id, args.revision, args.note)
        if op == "bind":
            if args.version_id is None or args.agent_id is None:
                fail(422, "bind requires version_id and agent_id")
            return await s.bind(db, user, args.workflow_id, args.version_id, args.agent_id)
        if op in {"test", "execute"}:
            if len(args.request_id) < 8:
                fail(422, "Use a unique request_id of 8 to 80 letters, digits, hyphen or underscore")
            if op == "execute" and args.version_id is None:
                fail(422, "execute requires version_id")
            return await self.engine.start(
                db,
                user,
                args.workflow_id,
                args.inputs,
                args.request_id,
                args.version_id if op == "execute" else None,
                actor.id,
            )
        fail(422, "Unknown operation")

    async def observe(
        self, db: AsyncSession, actor: AgentRun, target: Target | None, application_id: str | None = None
    ) -> dict:
        s = self.service
        async with s.lock:
            await s.assert_desktop_idle(db, ignore_agent_run=actor.id)
            held = (
                (
                    await db.execute(
                        select(AgentRun.id)
                        .where(AgentRun.tenant_id == actor.tenant_id, AgentRun.lane_held.is_(True))
                        .limit(257)
                    )
                )
                .scalars()
                .all()
            )
            if len(held) > 256:
                fail(409, "Too many active desktop task identities")
            session = "observe_" + actor.id.hex
            s.driver.runtime_contexts[session] = {
                "tenant_id": str(actor.tenant_id),
                "run_id": str(actor.id),
                "agent_id": str(actor.agent_id),
                "active_run_ids": [str(i) for i in held],
            }
            try:
                if application_id:
                    await s.driver.execute(
                        session,
                        Step(id="prepare_app", action="launch_app", app=application_id),
                        {},
                        "launch_" + uuid.uuid4().hex,
                        s.applications,
                    )
                frame = await s.driver.frame(session)
                windows = await s.driver.windows(session)
                text = ""
                if target:
                    w = await s.driver.find(session, target, {}, literal=True)
                    data = await s.driver.call(
                        session,
                        "get_window_state",
                        {"pid": w["pid"], "window_id": w["window_id"], "timeout_ms": 10000, "max_elements": 300},
                    )
                    text = result_text(data)[:18000]
                return {**frame, "windows": windows[:60], "window_count": len(windows), "window_text": text}
            finally:
                try:
                    await s.driver.release(session)
                except DriverFailure:
                    fail(409, "Desktop observation release is unconfirmed; inspect desktop ownership before continuing")
