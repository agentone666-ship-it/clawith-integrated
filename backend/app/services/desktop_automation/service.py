"""Authoritative workflow/version/recording state and authorization boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime
from typing import NoReturn

from fastapi import HTTPException
from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.tool import AgentTool, Tool
from app.models.user import User
from app.services.tool_config import encrypt_sensitive_fields

from .code_contracts import ManagedScript, PythonScript, kind, load_script
from .contracts import PARAMETER, Script, Step
from .driver import CuaDriver, DriverFailure
from .models import Playback, Recording, RecordingAction, Version, Workflow, now
from .settings import Settings


def fail(code: int, message: str) -> NoReturn:
    raise HTTPException(code, message)


def as_dict(row: object, fields: list[str]) -> dict:
    result = {}
    for key in fields:
        value = getattr(row, key)
        result[key] = (
            str(value) if isinstance(value, uuid.UUID) else value.isoformat() if isinstance(value, datetime) else value
        )
    return result


class AutomationService:
    def __init__(self, config: Settings):
        self.config = config
        self.driver = CuaDriver(config)
        self.lock = asyncio.Lock()
        self.tasks: dict[uuid.UUID, asyncio.Task] = {}
        self.recording_inputs: dict[uuid.UUID, dict[str, str]] = {}
        self.applications = json.loads(
            os.getenv(
                "AUTOMATION_APPLICATIONS",
                '{"notepad":{"label":"记事本","path":"C:\\\\Windows\\\\System32\\\\notepad.exe"}}',
            )
        )

    def authorize(self, user: User) -> uuid.UUID:
        if not user.tenant_id or str(user.tenant_id) != self.config.tenant_id:
            fail(403, "Your company has no configured recording desktop")
        if not user.is_active:
            fail(403, "Account is inactive")
        return user.tenant_id

    async def workflow(self, db: AsyncSession, user: User, ident: uuid.UUID, *, lock: bool = False) -> Workflow:
        tenant = self.authorize(user)
        stmt = select(Workflow).where(Workflow.id == ident, Workflow.tenant_id == tenant)
        if user.role not in {"org_admin", "platform_admin"}:
            stmt = stmt.where(Workflow.owner_id == user.id)
        if lock:
            stmt = stmt.with_for_update()
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            fail(404, "Workflow not found")
        return row

    async def list_workflows(self, db: AsyncSession, user: User, offset: int) -> list[dict]:
        tenant = self.authorize(user)
        stmt = select(Workflow).where(Workflow.tenant_id == tenant)
        if user.role not in {"org_admin", "platform_admin"}:
            stmt = stmt.where(Workflow.owner_id == user.id)
        rows = (await db.execute(stmt.order_by(Workflow.updated_at.desc()).offset(offset).limit(50))).scalars()
        return [
            {**as_dict(w, ["id", "name", "description", "revision", "updated_at"]), "kind": kind(load_script(w.draft))}
            for w in rows
        ]

    async def create(
        self, db: AsyncSession, user: User, name: str, description: str, script: ManagedScript | None = None
    ) -> dict:
        tenant = self.authorize(user)
        count = (
            await db.execute(select(func.count()).select_from(Workflow).where(Workflow.tenant_id == tenant))
        ).scalar_one()
        if count >= 500:
            fail(409, "Workflow limit reached")
        row = Workflow(
            tenant_id=tenant,
            owner_id=user.id,
            name=name,
            description=description,
            draft=(script or Script()).model_dump(),
        )
        db.add(row)
        await db.flush()
        return await self.detail(db, user, row.id)

    async def detail(self, db: AsyncSession, user: User, ident: uuid.UUID) -> dict:
        w = await self.workflow(db, user, ident)
        versions = (
            await db.execute(
                select(Version)
                .where(Version.workflow_id == w.id, Version.tenant_id == w.tenant_id)
                .order_by(Version.number.desc())
                .limit(100)
            )
        ).scalars()
        runs = (
            await db.execute(
                select(Playback)
                .where(Playback.workflow_id == w.id, Playback.tenant_id == w.tenant_id)
                .order_by(Playback.created_at.desc())
                .limit(40)
            )
        ).scalars()
        sessions = (
            (
                await db.execute(
                    select(Recording)
                    .where(
                        Recording.workflow_id == w.id,
                        Recording.tenant_id == w.tenant_id,
                        Recording.status.in_(["active", "release_pending"]),
                    )
                    .order_by(Recording.created_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .all()
        )
        return {
            **as_dict(w, ["id", "name", "description", "draft", "revision", "updated_at"]),
            "versions": [
                as_dict(
                    v,
                    [
                        "id",
                        "number",
                        "digest",
                        "note",
                        "tool_id",
                        "validation_run_id",
                        "compiler_fingerprint",
                        "created_at",
                    ],
                )
                for v in versions
            ],
            "runs": [self.run_view(r) for r in runs],
            "recording": self.record_view(sessions[0]) if sessions else None,
            "applications": [{"id": k, "label": v["label"]} for k, v in self.applications.items()],
        }

    async def edit(
        self,
        db: AsyncSession,
        user: User,
        ident: uuid.UUID,
        revision: int,
        script: ManagedScript,
        name: str,
        description: str,
    ) -> dict:
        w = await self.workflow(db, user, ident, lock=True)
        if w.revision != revision:
            fail(409, "Draft changed; refresh before saving")
        w.draft = script.model_dump()
        w.name, w.description = name, description
        w.revision += 1
        w.updated_at = now()
        await db.flush()
        return await self.detail(db, user, ident)

    async def version(self, db: AsyncSession, user: User, ident: uuid.UUID, version_id: uuid.UUID) -> Version:
        w = await self.workflow(db, user, ident)
        v = (
            await db.execute(
                select(Version).where(
                    Version.id == version_id, Version.workflow_id == ident, Version.tenant_id == w.tenant_id
                )
            )
        ).scalar_one_or_none()
        if not v:
            fail(404, "Version not found")
        return v

    def tool_token(self, tenant: uuid.UUID, version_id: uuid.UUID) -> str:
        return hmac.new(self.config.signing_key.encode(), f"{tenant}:{version_id}".encode(), hashlib.sha256).hexdigest()

    async def publish(self, db: AsyncSession, user: User, ident: uuid.UUID, revision: int, note: str) -> dict:
        w = await self.workflow(db, user, ident, lock=True)
        if w.revision != revision:
            fail(409, "Draft changed; validate and publish the current draft")
        script = load_script(w.draft)
        if isinstance(script, Script) and (
            not script.steps or not any(s.action == "assert_text" for s in script.steps)
        ):
            fail(409, "Add an explicit result verification step before publishing")
        proof = (
            await db.execute(
                select(Playback)
                .where(
                    Playback.workflow_id == ident,
                    Playback.tenant_id == w.tenant_id,
                    Playback.digest == script.digest(),
                    Playback.status == "succeeded",
                    Playback.version_id.is_(None),
                )
                .order_by(Playback.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if proof is None:
            fail(409, "This exact draft must pass a test before publication")
        if isinstance(script, PythonScript) and not proof.result.get("compiler_fingerprint"):
            fail(409, "Python draft requires a successful isolated test")
        num = (await db.execute(select(func.max(Version.number)).where(Version.workflow_id == ident))).scalar_one() or 0
        if num >= 100:
            fail(409, "This workflow reached its 100-version limit")
        v = Version(
            id=uuid.uuid4(),
            tenant_id=w.tenant_id,
            workflow_id=w.id,
            number=num + 1,
            script=script.model_dump(),
            digest=script.digest(),
            note=note,
            validation_run_id=proof.id,
            compiler_fingerprint=proof.result.get("compiler_fingerprint") if isinstance(script, PythonScript) else None,
        )
        tool = Tool(
            id=uuid.uuid4(),
            name=f"desktop_{w.id.hex[:12]}_v{v.number}",
            display_name=f"{w.name} · v{v.number}",
            description=w.description[:700]
            + " Execute the tested desktop automation with the supplied inputs. The published version is fixed. Success requires its recorded result checks. Do not retry an unknown write outcome; inspect the run result first.",
            type="mcp",
            category="custom",
            parameters_schema=script.input_schema(),
            mcp_server_url=self.config.public_mcp_url.rstrip("/") + "/" + str(v.id),
            mcp_server_name="Clawith desktop workflows",
            mcp_tool_name="run_workflow",
            enabled=True,
            is_default=False,
            source="admin",
            tenant_id=w.tenant_id,
            config=encrypt_sensitive_fields(
                {"api_key": self.tool_token(w.tenant_id, v.id), "runtime_context_meta": True}
            ),
        )
        v.tool_id = tool.id
        db.add_all([v, tool])
        await db.flush()
        return {
            "version_id": str(v.id),
            "number": v.number,
            "tool_id": str(tool.id),
            "validation_run_id": str(proof.id),
        }

    async def restore(
        self, db: AsyncSession, user: User, ident: uuid.UUID, version_id: uuid.UUID, revision: int
    ) -> dict:
        v = await self.version(db, user, ident, version_id)
        w = await self.workflow(db, user, ident, lock=True)
        if w.revision != revision:
            fail(409, "Draft changed; refresh first")
        w.draft = v.script
        w.revision += 1
        w.updated_at = now()
        return {"revision": w.revision, "restored_version": v.number}

    async def bind(
        self, db: AsyncSession, user: User, ident: uuid.UUID, version_id: uuid.UUID, agent_id: uuid.UUID
    ) -> dict:
        from .assignments import VersionAssignments

        await VersionAssignments(self).assign(db, user, ident, version_id, [agent_id])
        return {
            "agent_id": str(agent_id),
            "version_id": str(version_id),
            "tool_id": str((await self.version(db, user, ident, version_id)).tool_id),
        }

    async def assert_desktop_idle(
        self, db: AsyncSession, *, ignore_playback: uuid.UUID | None = None, ignore_agent_run: uuid.UUID | None = None
    ) -> None:
        raw_active = (
            await db.execute(
                select(AgentRun.id)
                .join(AgentTool, AgentTool.agent_id == AgentRun.agent_id)
                .where(
                    AgentTool.tool_id == uuid.UUID(self.config.driver_tool_id),
                    AgentTool.enabled.is_(True),
                    AgentRun.lane_held.is_(True),
                    AgentRun.id != ignore_agent_run if ignore_agent_run else true(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if raw_active:
            fail(409, "The Windows desktop is reserved by an active agent task")
        recording = (
            await db.execute(select(Recording.id).where(Recording.status.in_(["active", "release_pending"])).limit(1))
        ).scalar_one_or_none()
        if recording:
            fail(409, "The desktop has an active recording; stop it before replay")
        stmt = select(Playback.id).where(Playback.status == "running")
        if ignore_playback:
            stmt = stmt.where(Playback.id != ignore_playback)
        if (await db.execute(stmt.limit(1))).scalar_one_or_none():
            fail(409, "The desktop is replaying another workflow")

    @staticmethod
    def record_view(r: Recording) -> dict:
        return as_dict(r, ["id", "workflow_id", "status", "paused", "script", "last_seen"])

    @staticmethod
    def run_view(r: Playback) -> dict:
        view = as_dict(
            r,
            [
                "id",
                "workflow_id",
                "version_id",
                "agent_run_id",
                "status",
                "digest",
                "input_summary",
                "progress",
                "result",
                "cancel_requested",
                "created_at",
                "updated_at",
            ],
        )
        view["result"] = {k: v for k, v in (r.result or {}).items() if k != "compiled_plan"}
        return view

    async def recording(
        self, db: AsyncSession, user: User, ident: uuid.UUID, *, allow_release_pending: bool = False
    ) -> Recording:
        tenant = self.authorize(user)
        r = (
            await db.execute(
                select(Recording).where(
                    Recording.id == ident, Recording.tenant_id == tenant, Recording.owner_id == user.id
                )
            )
        ).scalar_one_or_none()
        if r is None:
            fail(404, "Recording not found")
        await self.workflow(db, user, r.workflow_id)
        if r.status != "active" and not (allow_release_pending and r.status == "release_pending"):
            fail(409, "Recording is no longer active")
        return r

    async def start_recording(self, db: AsyncSession, user: User, ident: uuid.UUID, revision: int) -> dict:
        async with self.lock:
            w = await self.workflow(db, user, ident, lock=True)
            if w.revision != revision:
                fail(409, "Draft changed; refresh first")
            if isinstance(load_script(w.draft), PythonScript):
                fail(409, "Python scripts are edited as source; create an RPA workflow to record")
            await self.assert_desktop_idle(db)
            r = Recording(
                id=uuid.uuid4(),
                tenant_id=w.tenant_id,
                owner_id=user.id,
                workflow_id=w.id,
                base_revision=w.revision,
                script=Script().model_dump(),
                status="active",
            )
            # Claim the native desktop before publishing an active recording.
            try:
                await self.driver.frame("record_" + r.id.hex)
            except DriverFailure as exc:
                fail(409, str(exc))
            db.add(r)
            await db.commit()
            return self.record_view(r)

    async def recording_frame(self, db: AsyncSession, user: User, ident: uuid.UUID) -> dict:
        async with self.lock:
            r = await self.recording(db, user, ident)
            r.last_seen = now()
            await db.commit()
            frame = await self.driver.frame("record_" + r.id.hex)
            return {**frame, "windows": await self.driver.windows("record_" + r.id.hex)}

    async def pause(self, db: AsyncSession, user: User, ident: uuid.UUID, paused: bool) -> dict:
        async with self.lock:
            r = await self.recording(db, user, ident)
            r.paused, r.last_seen = paused, now()
            await db.commit()
            return self.record_view(r)

    async def record_action(
        self,
        db: AsyncSession,
        user: User,
        ident: uuid.UUID,
        request_id: str,
        step: Step,
        parameter: str,
        parameter_label: str,
        secret: bool = False,
    ) -> dict:
        async with self.lock:
            r = await self.recording(db, user, ident)
            fingerprint = hashlib.sha256(
                json.dumps(
                    [step.model_dump(), parameter, parameter_label, secret], sort_keys=True, ensure_ascii=False
                ).encode()
            ).hexdigest()
            old = (
                await db.execute(
                    select(RecordingAction).where(
                        RecordingAction.recording_id == r.id, RecordingAction.request_id == request_id
                    )
                )
            ).scalar_one_or_none()
            if old:
                if old.fingerprint != fingerprint:
                    fail(409, "Request ID was already used for different input")
                return {"status": old.status, **old.result, "recording": self.record_view(r)}
            script = Script.model_validate(r.script)
            if len(script.steps) >= 120:
                fail(409, "Recording reached 120 steps; finish or edit this workflow")
            if parameter and (step.action != "type_text" or not PARAMETER.fullmatch("${" + parameter + "}")):
                fail(422, "A parameter requires a valid name and a text-input action")
            anchored = await self.driver.anchor("record_" + r.id.hex, step)
            values = dict(self.recording_inputs.get(r.id, {}))
            if parameter and not r.paused:
                values[parameter] = anchored.text
                self.recording_inputs[r.id] = values
                anchored = anchored.model_copy(update={"text": "${" + parameter + "}"})
                script.parameters[parameter] = parameter_label or parameter
                if secret and parameter not in script.secret_parameters:
                    script.secret_parameters.append(parameter)
            # A verification explicitly confirms a paused, uncertain input.
            capture_step = not r.paused or step.action == "assert_text"
            # Validate the complete prospective script before dispatching input.
            if capture_step:
                steps = list(script.steps)
                if (
                    anchored.action == "type_text"
                    and not parameter
                    and steps
                    and steps[-1].action == "type_text"
                    and steps[-1].target == anchored.target
                    and not PARAMETER.search(steps[-1].text)
                ):
                    steps[-1] = steps[-1].model_copy(update={"text": steps[-1].text + anchored.text})
                else:
                    steps.append(anchored)
                prospective = Script.model_validate({**script.model_dump(), "steps": [s.model_dump() for s in steps]})
            else:
                prospective = script
            # Resolve all authored parameters before a durable dispatch receipt.
            from .contracts import render

            render(anchored.text, values)
            if anchored.target:
                render(anchored.target.title, values)
            action = RecordingAction(
                recording_id=r.id, request_id=request_id, fingerprint=fingerprint, status="dispatched", result={}
            )
            db.add(action)
            r.last_seen = now()
            await db.commit()
            status, detail = "recorded", "操作已记录" if not r.paused else "操作已执行，录制已暂停"
            try:
                await self.driver.execute("record_" + r.id.hex, anchored, values, request_id, self.applications)
            except DriverFailure as exc:
                status, detail = ("unknown" if exc.uncertain else "failed"), str(exc)
                r.paused = True
            if status == "recorded" and step.action == "assert_text":
                r.paused = False
            if status == "recorded" and capture_step:
                r.script = prospective.model_dump()
            elif status == "unknown":
                # Preserve the attempted step for explicit review and validation;
                # the recorder pauses and never silently repeats the input.
                r.script = prospective.model_dump()
            action.status = status
            action.result = {"detail": detail}
            r.last_seen = now()
            await db.commit()
            return {"status": status, "detail": detail, "recording": self.record_view(r)}

    async def stop_recording(self, db: AsyncSession, user: User, ident: uuid.UUID) -> dict:
        async with self.lock:
            r = await self.recording(db, user, ident, allow_release_pending=True)
            w = await self.workflow(db, user, r.workflow_id, lock=True)
            try:
                await self.driver.release("record_" + r.id.hex)
            except DriverFailure as exc:
                r.status = "release_pending"
                await db.commit()
                fail(409, "Desktop release remains unconfirmed: " + str(exc))
            r.status = "stopped"
            self.recording_inputs.pop(r.id, None)
            if w.revision != r.base_revision:
                r.status = "conflict"
                await db.commit()
                fail(
                    409,
                    "Draft changed during recording. Recorded steps remain saved in this session; the existing draft was not overwritten.",
                )
            w.draft, w.updated_at = r.script, now()
            w.revision += 1
            await db.commit()
            return self.record_view(r)
