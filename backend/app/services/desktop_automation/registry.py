"""Agent-authored source registry, sharing the manual studio lifecycle and policy."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.tool import AgentTool, Tool
from app.models.user import User
from app.services.tool_config import encrypt_sensitive_fields

from .code_contracts import ManagedScript
from .contracts import Script, Target
from .driver import DriverFailure, result_text
from .executor import PlaybackEngine
from .registry_schema import registry_schema
from .scaffold import python_template
from .service import AutomationService, fail

SDK = """自动化管理 Tool 使用说明：
1. sdk 获取说明；list/get/version 查看已有 RPA 步骤或 Python 源码。RPA 会附 python_template 脚手架，可保留其全部已验证动作/坐标/弹窗交互，只改参数计算，避免重新猜坐标。get 的 source_offset 可分页读取源码。
2. observe 观察服务器独立 Windows 桌面；传 target={app,title} 可获取该窗口的控件文本。点击坐标是窗口左上角为原点的相对坐标，不是截图全屏坐标。不要猜坐标。
3. create(name,description,script) 新建；update(workflow_id,revision,name,description,script) 保存。并发修改会拒绝，请重新 get。
4. test(workflow_id,inputs,request_id) 等待试运行结果；失败看 result.diagnostic.line / failed_source_line / failed_step。修改后重新 test。
5. publish(workflow_id,revision,note) 只允许当前源码完整摘要已有成功试运行。返回固定 version_id 和 tool_id。
6. bind(workflow_id,version_id,agent_id) 把版本 Tool 分配给有权配置的业务 Agent。业务 Agent 调用 run_workflow，不需要管理 Tool。
7. execute 仅可执行当前 Agent 已绑定的版本 Tool；管理 Tool 本身不会授予运行所有版本的权限。
Python 格式：{"format":"clawith.python.v1","source":"...","parameters":{"order":"单号"},"secret_parameters":[]}
Python 示例：
from automation import ui, inputs
from decimal import Decimal
w = ui.window("notepad.exe", "*Notepad*")
ui.launch("notepad")
ui.type_text(inputs["order"], target=w)
ui.assert_text(inputs["order"], target=w)
SDK: ui.window(app,title), ui.launch(server_app_id), ui.click/double_click/right_click(x,y,target=w), ui.type_text(str,target=w), ui.key("tab",target=w), ui.hotkey("ctrl","s",target=w), ui.scroll("down",3,target=w), ui.assert_text(text,target=w,timeout_seconds=8)。各动作可带 label。
纯 Python 只做参数计算、循环、条件分支和动作编排；它先在隔离环境产生有上限的动作计划，再执行桌面动作，不能在脚本里读界面或访问网络/文件/进程。先 observe 获取当前界面，或复用已有录制步骤。可用计算库 decimal/math/json/re/datetime/itertools/statistics。输入都是字符串。敏感参数仅能直接传 ui.type_text，不能拼接、计算或输出。不要在源码写凭据。
每次操作最多120步，输入总32KiB，源码及参数总128KiB；一次桌面执行180秒。必须显式 ui.assert_text 校验结果。未知写入结果不可盲重试；先观察业务状态。新业务操作使用新的 request_id，同一操作查询/重试沿用相同ID。不得通过声明假的成功条件绕过验证。
"""


class RegistryCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal[
        "sdk",
        "list",
        "get",
        "version",
        "observe",
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
        if op == "observe":
            return await self.observe(db, actor, args.target)
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

    async def observe(self, db: AsyncSession, actor: AgentRun, target: Target | None) -> dict:
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
