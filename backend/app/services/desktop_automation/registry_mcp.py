"""MCP transport for automation source management; identity never comes from arguments."""

import asyncio
import base64
import json
import secrets
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.database import async_session
from app.models.tool import Tool

from .driver import DriverFailure
from .models import Playback
from .registry import RegistryCall
from .registry_schema import registry_schema

router = APIRouter()


@router.post("/api/automation-mcp/registry")
async def registry_mcp(req: Request):
    registry = req.app.state.automation_registry
    s = registry.service
    expected = "Bearer " + s.tool_token(uuid.UUID(s.config.tenant_id), registry.tool_id)
    if not secrets.compare_digest(req.headers.get("authorization", ""), expected):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    raw = bytearray()
    async for chunk in req.stream():
        raw.extend(chunk)
        if len(raw) > 196608:
            return JSONResponse({"error": "Request exceeds 192 KiB"}, status_code=413)
    try:
        body = json.loads(raw)
        if not isinstance(body, dict) or not isinstance(body.get("params", {}), dict):
            raise TypeError("Invalid MCP request")
    except (ValueError, TypeError):
        return JSONResponse({"error": "Invalid JSON request"}, status_code=400)
    method = body.get("method")
    async with async_session() as db:
        tool = await db.get(Tool, registry.tool_id)
        if not tool or not tool.enabled:
            return JSONResponse({"error": "Management Tool is disabled"}, status_code=403)
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "clawith-automation-registry", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "automation_registry",
                        "description": tool.description,
                        "inputSchema": registry_schema(),
                    }
                ]
            }
        elif method == "tools/call":
            try:
                params = body["params"]
                if params.get("name") != "automation_registry":
                    raise ValueError("Unknown automation management Tool")
                envelope = params.get("_meta") or {}
                meta = envelope.get("io.clawith/runtime", {}) if isinstance(envelope, dict) else {}
                if not isinstance(meta, dict):
                    raise TypeError("Invalid Runtime identity")
                args = RegistryCall.model_validate(params.get("arguments"))
                value = await registry.invoke(db, meta, args)
                await db.commit()
                if args.operation in {"test", "execute"} and value.get("status") == "running":
                    task = s.tasks.get(uuid.UUID(value["id"]))
                    if task:
                        await asyncio.shield(task)
                    await db.rollback()
                    db.expire_all()
                    row = await db.get(Playback, uuid.UUID(value["id"]))
                    value = s.run_view(row) if row else {"error": "Execution receipt unavailable"}
                content = []
                if args.operation in {"observe", "launch"}:
                    content.append({"type": "image", "mimeType": value.pop("mime"), "data": value.pop("image")})
                text = json.dumps(value, ensure_ascii=False)
                if len(text.encode()) > 60000:
                    raise ValueError("Result exceeds model context budget; use a smaller source or result page")
                content.insert(0, {"type": "text", "text": text})
                execution_result = value.get("result")
                if (
                    args.operation in {"test", "execute"}
                    and isinstance(execution_result, dict)
                    and execution_result.get("evidence")
                ):
                    path = s.config.evidence_dir / value["id"] / "final.png"
                    if path.is_file():
                        raw_image = path.read_bytes()
                        if len(raw_image) <= 6 * 1024 * 1024:
                            content.append(
                                {"type": "image", "mimeType": "image/png", "data": base64.b64encode(raw_image).decode()}
                            )
                result = {"isError": value.get("status") in {"failed", "unknown", "cancelled"}, "content": content}
            except ValidationError as exc:
                await db.rollback()
                errors = exc.errors(include_url=False, include_input=False)[:5]
                message = (
                    "参数校验失败。script / inputs / target 必须是原生 JSON 对象。workflow_id、revision、name 应放外层，不能放在 script 内。请只修复下列字段："
                    + json.dumps(errors, ensure_ascii=False, default=str)
                )
                result = {"isError": True, "content": [{"type": "text", "text": message[:2000]}]}
            except (HTTPException, ValueError, TypeError, DriverFailure) as exc:
                await db.rollback()
                message = exc.detail if isinstance(exc, HTTPException) else str(exc)
                result = {"isError": True, "content": [{"type": "text", "text": str(message)[:2000]}]}
        elif method in {"notifications/initialized", "ping"}:
            result = {}
        else:
            result = {"isError": True, "content": [{"type": "text", "text": "Unsupported MCP method"}]}
    return {"jsonrpc": "2.0", "id": body.get("id"), "result": result}
