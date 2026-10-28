"""Published immutable workflows as ordinary opt-in Clawith MCP Tools."""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.database import async_session
from app.models.agent_run import AgentRun
from app.models.tool import AgentTool, Tool
from app.models.user import User

from .code_contracts import load_script
from .models import Playback, Version, Workflow

router = APIRouter()


@router.post("/api/automation-mcp/{version_id}")
async def mcp(req: Request, version_id: uuid.UUID):
    service = req.app.state.desktop_automation
    engine = req.app.state.desktop_playback
    raw = bytearray()
    async for chunk in req.stream():
        raw.extend(chunk)
        if len(raw) > 65536:
            return JSONResponse({"error": "Request too large"}, status_code=413)
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    if not isinstance(body, dict) or not isinstance(body.get("params", {}), dict):
        return JSONResponse({"error": "Invalid MCP request"}, status_code=400)
    async with async_session() as db:
        version = await db.get(Version, version_id)
        if (
            version is None
            or str(version.tenant_id) != service.config.tenant_id
            or not secrets.compare_digest(
                req.headers.get("authorization", ""), "Bearer " + service.tool_token(version.tenant_id, version_id)
            )
        ):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        tool = await db.get(Tool, version.tool_id)
        if tool is None or not tool.enabled:
            return JSONResponse({"error": "Tool is disabled"}, status_code=403)
        script = load_script(version.script)
        method, ident = body.get("method"), body.get("id")
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "clawith-desktop-workflows", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {"name": "run_workflow", "description": tool.description, "inputSchema": script.input_schema()}
                ]
            }
        elif method == "tools/call":
            try:
                params = body.get("params", {})
                if params.get("name") != "run_workflow":
                    raise ValueError("Unknown workflow tool")
                envelope = params.get("_meta") or {}
                if not isinstance(envelope, dict):
                    raise TypeError("Invalid Runtime metadata")
                meta = envelope.get("io.clawith/runtime", {})
                if not isinstance(meta, dict) or any(
                    not isinstance(meta.get(k), str) for k in ("run_id", "agent_id", "tenant_id")
                ):
                    raise ValueError("An authenticated Clawith Runtime identity is required")
                runtime_id = uuid.UUID(meta.get("run_id", ""))
                agent_id = uuid.UUID(meta.get("agent_id", ""))
                tenant_id = uuid.UUID(meta.get("tenant_id", ""))
                run = (
                    await db.execute(
                        select(AgentRun).where(
                            AgentRun.id == runtime_id,
                            AgentRun.agent_id == agent_id,
                            AgentRun.tenant_id == tenant_id,
                            AgentRun.lane_held.is_(True),
                        )
                    )
                ).scalar_one_or_none()
                binding = (
                    await db.execute(
                        select(AgentTool.id)
                        .where(
                            AgentTool.agent_id == agent_id, AgentTool.tool_id == tool.id, AgentTool.enabled.is_(True)
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if run is None or binding is None or tenant_id != version.tenant_id:
                    raise ValueError("This workflow requires an active authorized Clawith Run and assigned Tool")
                workflow = await db.get(Workflow, version.workflow_id)
                user = await db.get(User, workflow.owner_id) if workflow else None
                if workflow is None or user is None:
                    raise ValueError("Workflow owner is unavailable")
                if not isinstance(params.get("arguments"), dict):
                    raise TypeError("Workflow arguments must be an object")
                arguments = dict(params["arguments"])
                request_id = arguments.pop("_operation_id", "")
                if not isinstance(request_id, str) or not 8 <= len(request_id) <= 80:
                    raise ValueError("A unique _operation_id is required; reuse it only for the same operation")
                row = await engine.start(db, user, workflow.id, arguments, request_id, version_id, runtime_id)
                playback_id = uuid.UUID(row["id"])
                task = service.tasks.get(playback_id)
                if task:
                    await asyncio.shield(task)
                await db.rollback()
                db.expire_all()
                r = await db.get(Playback, playback_id)
                if r is None:
                    raise ValueError("Workflow execution receipt is unavailable")
                view = service.run_view(r)
                content = [{"type": "text", "text": json.dumps(view, ensure_ascii=False)}]
                path = service.config.evidence_dir / str(playback_id) / "final.png"
                if r.result.get("evidence") and path.is_file():
                    image = path.read_bytes()
                    if len(image) <= 6 * 1024 * 1024:
                        content.append(
                            {"type": "image", "mimeType": "image/png", "data": base64.b64encode(image).decode()}
                        )
                result = {"isError": r.status != "succeeded", "content": content}
            except (ValueError, TypeError, HTTPException) as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                result = {"isError": True, "content": [{"type": "text", "text": str(detail)[:1200]}]}
        elif method in {"notifications/initialized", "ping"}:
            result = {}
        else:
            result = {"isError": True, "content": [{"type": "text", "text": "Unsupported MCP method"}]}
    return {"jsonrpc": "2.0", "id": ident, "result": result}
