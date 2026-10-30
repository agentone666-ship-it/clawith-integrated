"""Private host service. Only the authenticated capability supplies owner scope."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .manager import Manager, SandboxError
from .provider import Libvirt


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: uuid.UUID
    owner_id: uuid.UUID
    agent_id: uuid.UUID | None = None


class Call(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope
    operation: str = Field(pattern=r"^(run|record|play)_[a-f0-9]{32}$")
    nonce: str = Field(min_length=32, max_length=128)
    body: dict = Field(default_factory=dict)


async def reap(manager):
    while True:
        await asyncio.sleep(10)
        try:
            await manager.sweep()
        except SandboxError:
            logging.getLogger(__name__).exception("Windows reclamation needs operator attention")


@asynccontextmanager
async def lifespan(app):
    root = Path(os.environ["WINDOWS_SANDBOX_ROOT"])
    state = Path(os.environ["WINDOWS_SANDBOX_STATE"])
    token = Path(os.environ["WINDOWS_SANDBOX_TOKEN_FILE"]).read_text().strip()
    if len(token) < 32:
        raise RuntimeError("Sandbox authentication is incomplete")
    app.state.token = token
    app.state.manager = Manager(
        state / "state.sqlite",
        Libvirt(root, Path(os.getenv("WINDOWS_SANDBOX_TEMPLATE", str(root / "template/system.qcow2")))),
        idle_seconds=int(os.getenv("WINDOWS_SANDBOX_IDLE_SECONDS", "600")),
        max_running=int(os.getenv("WINDOWS_SANDBOX_MAX_RUNNING", "2")),
    )
    worker = asyncio.create_task(reap(app.state.manager))
    yield
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)
    app.state.manager.db.close()


app = FastAPI(title="Clawith Windows Sandbox Host", lifespan=lifespan)


@app.middleware("http")
async def authenticate(request: Request, call_next):
    if not secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + request.app.state.token):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 131072:
            return JSONResponse({"detail": "Request exceeds 128 KiB"}, status_code=413)
    request._body = bytes(raw)
    return await call_next(request)


@app.exception_handler(SandboxError)
async def failure(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@app.post("/v1/call")
async def call(request: Request, body: Call):
    return await request.app.state.manager.call(
        body.scope.model_dump(mode="json"), body.operation, body.nonce, body.body
    )


@app.post("/v1/heartbeat")
async def heartbeat(request: Request, body: Call):
    request.app.state.manager.heartbeat(body.scope.model_dump(mode="json"), body.operation, body.nonce)
    return {"ok": True}


@app.post("/v1/release")
async def release(request: Request, body: Call):
    await request.app.state.manager.release(body.scope.model_dump(mode="json"), body.operation, body.nonce, body.body)
    return {"ok": True}


@app.get("/v1/desktops")
async def desktops(request: Request, tenant: uuid.UUID, owner: uuid.UUID):
    return request.app.state.manager.listing(str(tenant), str(owner))


@app.post("/v1/desktops/{ident}/{action}")
async def desktop_action(request: Request, ident: uuid.UUID, action: str, body: Scope):
    manager = request.app.state.manager
    manager.authorize(str(ident), str(body.tenant_id), str(body.owner_id))
    if action == "save":
        await manager.suspend(str(ident))
    elif action == "start":
        try:
            await manager.prepare(str(ident))
        except SandboxError as exc:
            if exc.status != 425:
                raise
    else:
        raise HTTPException(404, "Unknown desktop operation")
    return manager.view(manager.row(str(ident)))
