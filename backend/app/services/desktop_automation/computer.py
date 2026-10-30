"""Runtime-owned atomic Cua Tool and private, read-only desktop preview."""

import asyncio
import json
import logging
import secrets
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.database import async_session
from app.models.agent_run import AgentRun
from app.models.tool import AgentTool, Tool
from app.models.user import User

from .driver import DesktopPreparing, DriverFailure
from .live import read_frame, store
from .service import fail

router = APIRouter()
log = logging.getLogger(__name__)


class Computer:
    def __init__(self, service):
        self.service = service
        self.tasks: dict[uuid.UUID, asyncio.Task] = {}

    async def actor(self, db, meta):
        try:
            ident, agent, tenant = (uuid.UUID(meta[k]) for k in ("run_id", "agent_id", "tenant_id"))
        except (ValueError, KeyError, TypeError, AttributeError):
            fail(403, "A genuine active Runtime identity is required")
        actor = await db.get(AgentRun, ident)
        tool_id = uuid.UUID(self.service.config.driver_tool_id)
        tool = await db.get(Tool, tool_id)
        binding = (
            await db.execute(
                select(AgentTool.id)
                .where(AgentTool.agent_id == agent, AgentTool.tool_id == tool_id, AgentTool.enabled.is_(True))
                .limit(1)
            )
        ).scalar_one_or_none()
        if (
            not actor
            or not actor.lane_held
            or actor.agent_id != agent
            or actor.tenant_id != tenant
            or str(tenant) != self.service.config.tenant_id
            or not actor.origin_user_id
            or not tool
            or not tool.enabled
            or not binding
        ):
            fail(403, "An active assigned Agent Run with a task origin user is required")
        origin = await db.get(User, actor.origin_user_id)
        if origin is None or origin.tenant_id != tenant:
            fail(403, "An authenticated task origin user is required")
        self.service.authorize(origin)
        return actor

    async def capture(self, actor, session):
        frame = await self.service.driver.frame(session)
        store(self.service, "computer/" + str(actor.id), frame)

    async def watch(self, actor, session):
        try:
            while True:
                await asyncio.sleep(0.8)
                async with async_session() as db:
                    current = await db.get(AgentRun, actor.id)
                    if not current or not current.lane_held:
                        return
                try:
                    async with self.service.lock:
                        await self.capture(actor, session)
                except (DriverFailure, OSError, ValueError):
                    # Capture failure must not replay input or claim task success.
                    log.warning("Computer preview capture delayed for %s", actor.id, exc_info=True)
        finally:
            async with self.service.lock:
                await self.service.driver.release(session)

    async def stop(self, ident):
        task = self.tasks.pop(ident, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def close(self):
        for ident in list(self.tasks):
            await self.stop(ident)

    async def call(self, db, actor, args):
        s = self.service
        session = "computer_" + actor.id.hex
        if args.get("action") == "release":
            await self.stop(actor.id)
            async with s.lock:
                await s.driver.release(session)
            return {"content": [{"type": "text", "text": "Desktop released; last captured frame retained."}]}
        for ident, task in list(self.tasks.items()):
            if task.done():
                self.tasks.pop(ident)
        async with s.lock:
            await s.assert_desktop_idle(db, ignore_agent_run=actor.id)
            active = await s.desktop_active_runs(db, actor)
            s.driver.runtime_contexts[session] = {
                "run_id": str(actor.id),
                "agent_id": str(actor.agent_id),
                "tenant_id": str(actor.tenant_id),
                "active_run_ids": [str(i) for i in active],
            }
            origin = await db.get(User, actor.origin_user_id)
            if origin is None:
                fail(403, "Desktop origin account is unavailable")
            s.bind_desktop(session, origin, actor=actor)
            # Initial capture makes the viewer available before a slow action.
            await self.capture(actor, session)
            if s.config.sandbox_url:
                await db.refresh(actor)
                if not actor.lane_held:
                    fail(403, "Task ended while the desktop was preparing; no input was dispatched")
            if actor.id not in self.tasks or self.tasks[actor.id].done():
                # Completed watchers no longer own provider state.
                self.tasks[actor.id] = asyncio.create_task(self.watch(actor, session))
            result = await s.driver.call(session, args.get("action"), args.get("params", {}), args.get("request_id"))
            try:
                await self.capture(actor, session)
            except DriverFailure:
                log.warning(
                    "Computer after-frame unavailable for %s", actor.id, exc_info=True
                )  #  # Preserve the action receipt even when its after-frame is unavailable.
            return result


async def latest(service, db, user, ident):
    tenant = service.authorize(user)
    actor = await db.get(AgentRun, ident)
    if not actor or actor.tenant_id != tenant or actor.origin_user_id != user.id:
        fail(404, "Desktop task not found")
    return read_frame(service.config.evidence_dir / "computer" / str(ident) / "live.png")


@router.post("/api/automation-mcp/computer")
async def computer_mcp(req: Request):
    computer = req.app.state.desktop_computer
    s = computer.service
    expected = "Bearer " + s.tool_token(uuid.UUID(s.config.tenant_id), uuid.UUID(s.config.driver_tool_id))
    if not secrets.compare_digest(req.headers.get("authorization", ""), expected):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    raw = bytearray()
    async for chunk in req.stream():
        raw.extend(chunk)
        if len(raw) > 131072:
            return JSONResponse({"error": "Request too large"}, status_code=413)
    body = {}
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise TypeError("Invalid MCP request")
        params = body.get("params") or {}
        if not isinstance(params, dict):
            raise TypeError("Invalid MCP params")
        if body.get("method") == "tools/call":
            if params.get("name") != "computer":
                raise ValueError("Unknown Tool")
            args = params.get("arguments")
            if not isinstance(args, dict) or set(args) - {"action", "params", "request_id"}:
                raise ValueError("Use action, params and request_id; Runtime owns identity")
            async with async_session() as db:
                envelope = params.get("_meta") or {}
                if not isinstance(envelope, dict):
                    raise TypeError("Invalid Runtime metadata")
                actor = await computer.actor(db, envelope.get("io.clawith/runtime", {}))
                result = await computer.call(db, actor, args)
            return {"jsonrpc": "2.0", "id": body.get("id"), "result": result}
        if body.get("method") == "tools/list":
            import httpx

            async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
                r = await client.post(
                    s.config.driver_url, json=body, headers={"Authorization": "Bearer " + s.config.driver_token}
                )
                r.raise_for_status()
                return r.json()
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "clawith-cua-computer", "version": "1"},
            },
        }
    except DesktopPreparing as exc:
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {"isError": False, "content": [{"type": "text", "text": str(exc)}]},
        }
    except (HTTPException, ValueError, TypeError, DriverFailure) as exc:
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return {
            "jsonrpc": "2.0",
            "id": body.get("id") if isinstance(body, dict) else None,
            "result": {"isError": True, "content": [{"type": "text", "text": str(message)[:1500]}]},
        }
