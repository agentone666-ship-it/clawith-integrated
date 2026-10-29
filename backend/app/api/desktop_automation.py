"""Transport for the native Clawith desktop recording and workflow library."""

from __future__ import annotations

import base64
import uuid
from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.desktop_automation.code_contracts import ManagedScript
from app.services.desktop_automation.contracts import Step
from app.services.desktop_automation.service import fail

CurrentUser: TypeAlias = Annotated[User, Depends(get_current_user)]
DBSession: TypeAlias = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/automations", tags=["desktop-automation"])


class WorkflowFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class Create(WorkflowFields):
    script: ManagedScript | None = None


class Draft(WorkflowFields):
    revision: int = Field(ge=0)
    script: ManagedScript


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)


class Publish(Revision):
    note: str = Field(default="", max_length=500)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=60, pattern=r"^[a-zA-Z0-9_-]+$")
    step: Step
    parameter_name: str = Field(default="", max_length=40)
    parameter_label: str = Field(default="", max_length=120)
    secret: bool = False


class Pause(BaseModel):
    paused: bool


class Test(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: dict[str, str] = Field(default_factory=dict, max_length=40)
    request_id: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    version_id: uuid.UUID | None = None


class Bind(BaseModel):
    agent_id: uuid.UUID


class BatchBind(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


def capability(req: Request):
    return req.app.state.desktop_automation


@router.get("")
async def listing(req: Request, user: CurrentUser, db: DBSession, offset: int = 0):
    if offset < 0 or offset > 10000:
        fail(422, "Invalid offset")
    return await capability(req).list_workflows(db, user, offset)


@router.post("")
async def create(req: Request, body: Create, user: CurrentUser, db: DBSession):
    return await capability(req).create(db, user, body.name, body.description, body.script)


@router.get("/registry")
async def registry_status(req: Request, user: CurrentUser, db: DBSession):
    return await req.app.state.automation_registry.status(db, user)


@router.post("/registry")
async def registry_register(req: Request, user: CurrentUser, db: DBSession):
    return await req.app.state.automation_registry.register(db, user)


@router.post("/registry/bind")
async def registry_bind(req: Request, body: Bind, user: CurrentUser, db: DBSession):
    return await req.app.state.automation_registry.bind_manager(db, user, body.agent_id)


@router.get("/authoring")
async def authoring_guide(req: Request, user: CurrentUser, db: DBSession, search: str = "", offset: int = 0):
    from app.services.desktop_automation.authoring import AuthoringGuide

    return await AuthoringGuide(req.app.state.automation_registry).readiness(db, user, search, offset)


@router.get("/{ident}")
async def detail(req: Request, ident: uuid.UUID, user: CurrentUser, db: DBSession):
    return await capability(req).detail(db, user, ident)


@router.put("/{ident}")
async def edit(req: Request, ident: uuid.UUID, body: Draft, user: CurrentUser, db: DBSession):
    return await capability(req).edit(db, user, ident, body.revision, body.script, body.name, body.description)


@router.post("/{ident}/recordings")
async def start_recording(req: Request, ident: uuid.UUID, body: Revision, user: CurrentUser, db: DBSession):
    return await capability(req).start_recording(db, user, ident, body.revision)


@router.get("/recordings/{ident}/frame")
async def recording_frame(req: Request, ident: uuid.UUID, user: CurrentUser, db: DBSession):
    return await capability(req).recording_frame(db, user, ident)


@router.post("/recordings/{ident}/actions")
async def record_action(req: Request, ident: uuid.UUID, body: Action, user: CurrentUser, db: DBSession):
    return await capability(req).record_action(
        db, user, ident, body.request_id, body.step, body.parameter_name, body.parameter_label, body.secret
    )


@router.post("/recordings/{ident}/pause")
async def pause(req: Request, ident: uuid.UUID, body: Pause, user: CurrentUser, db: DBSession):
    return await capability(req).pause(db, user, ident, body.paused)


@router.post("/recordings/{ident}/stop")
async def stop(req: Request, ident: uuid.UUID, user: CurrentUser, db: DBSession):
    return await capability(req).stop_recording(db, user, ident)


@router.post("/{ident}/test")
async def test(req: Request, ident: uuid.UUID, body: Test, user: CurrentUser, db: DBSession):
    return await req.app.state.desktop_playback.start(db, user, ident, body.inputs, body.request_id, body.version_id)


@router.get("/runs/{ident}/status")
async def run_status(req: Request, ident: uuid.UUID, user: CurrentUser, db: DBSession):
    r = await req.app.state.desktop_playback.get(db, user, ident)
    return capability(req).run_view(r)


@router.post("/runs/{ident}/cancel")
async def cancel(req: Request, ident: uuid.UUID, user: CurrentUser, db: DBSession):
    return await req.app.state.desktop_playback.cancel(db, user, ident)


@router.get("/runs/{ident}/evidence")
async def evidence(req: Request, ident: uuid.UUID, user: CurrentUser, db: DBSession):
    r = await req.app.state.desktop_playback.get(db, user, ident)
    path = capability(req).config.evidence_dir / str(r.id) / "final.png"
    if not r.result.get("evidence") or not path.is_file():
        fail(404, "No final screenshot is available")
    return {"image": base64.b64encode(path.read_bytes()).decode(), "mime": "image/png"}


@router.post("/{ident}/versions")
async def publish(req: Request, ident: uuid.UUID, body: Publish, user: CurrentUser, db: DBSession):
    return await capability(req).publish(db, user, ident, body.revision, body.note)


@router.get("/{ident}/versions/{version_id}")
async def version(req: Request, ident: uuid.UUID, version_id: uuid.UUID, user: CurrentUser, db: DBSession):
    v = await capability(req).version(db, user, ident, version_id)
    return {
        "id": str(v.id),
        "number": v.number,
        "script": v.script,
        "digest": v.digest,
        "note": v.note,
        "tool_id": str(v.tool_id) if v.tool_id else None,
    }


@router.post("/{ident}/versions/{version_id}/restore")
async def restore(
    req: Request, ident: uuid.UUID, version_id: uuid.UUID, body: Revision, user: CurrentUser, db: DBSession
):
    return await capability(req).restore(db, user, ident, version_id, body.revision)


@router.post("/{ident}/versions/{version_id}/bind")
async def bind(req: Request, ident: uuid.UUID, version_id: uuid.UUID, body: Bind, user: CurrentUser, db: DBSession):
    return await capability(req).bind(db, user, ident, version_id, body.agent_id)


@router.get("/{ident}/versions/{version_id}/agents")
async def assignment_candidates(
    req: Request,
    ident: uuid.UUID,
    version_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
    search: str = "",
    offset: int = 0,
):
    from app.services.desktop_automation.assignments import VersionAssignments

    if len(search) > 120 or not 0 <= offset <= 10000:
        fail(422, "Invalid search or offset")
    return await VersionAssignments(capability(req)).candidates(db, user, ident, version_id, search.strip(), offset)


@router.post("/{ident}/versions/{version_id}/assignments")
async def batch_assign(
    req: Request, ident: uuid.UUID, version_id: uuid.UUID, body: BatchBind, user: CurrentUser, db: DBSession
):
    from app.services.desktop_automation.assignments import VersionAssignments

    return await VersionAssignments(capability(req)).assign(db, user, ident, version_id, body.agent_ids)


@router.get("/runs/{ident}/frames/{step}")
async def playback_frame(req: Request, ident: uuid.UUID, step: int, user: CurrentUser, db: DBSession):
    from app.services.desktop_automation.trace import frame

    return await frame(req.app.state.desktop_playback, db, user, ident, step)


@router.get("/agent-runs/{agent_id}")
async def latest_agent_playback(req: Request, agent_id: uuid.UUID, user: CurrentUser, db: DBSession):
    from app.services.desktop_automation.trace import latest

    return await latest(req.app.state.desktop_playback, db, user, agent_id)


@router.get("/agent-activity/{agent_id}")
async def agent_activity(req: Request, agent_id: uuid.UUID, session_id: uuid.UUID, user: CurrentUser, db: DBSession):
    from app.services.desktop_automation.trace import activity

    return await activity(req.app.state.desktop_playback, db, user, agent_id, session_id)
