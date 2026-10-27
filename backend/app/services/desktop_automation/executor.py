"""Bounded playback, durable results and resource cleanup for one desktop worker."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.agent_run import AgentRun
from app.models.user import User

from .contracts import Script
from .driver import DriverFailure
from .models import Playback, Recording, Workflow, now
from .service import AutomationService, fail


class PlaybackEngine:
    def __init__(self, service: AutomationService):
        self.service = service

    async def start(
        self,
        db: AsyncSession,
        user: User,
        workflow_id: uuid.UUID,
        inputs: dict[str, str],
        request_id: str,
        version_id: uuid.UUID | None = None,
        agent_run_id: uuid.UUID | None = None,
    ) -> dict:
        async with self.service.lock:
            w = await self.service.workflow(db, user, workflow_id)
            if version_id:
                v = await self.service.version(db, user, workflow_id, version_id)
                script = Script.model_validate(v.script)
            else:
                script = Script.model_validate(w.draft)
            if not script.steps or not any(s.action == "assert_text" for s in script.steps):
                fail(422, "Record steps and add a result verification before testing")
            script.validate_inputs(inputs)
            fingerprint = hashlib.sha256(
                json.dumps(
                    [script.digest(), inputs, str(version_id), str(agent_run_id)], sort_keys=True, ensure_ascii=False
                ).encode()
            ).hexdigest()
            old = (
                await db.execute(
                    select(Playback).where(Playback.tenant_id == w.tenant_id, Playback.request_id == request_id)
                )
            ).scalar_one_or_none()
            if old:
                if old.owner_id != user.id or old.fingerprint != fingerprint:
                    fail(409, "Request ID was already used for another operation")
                return self.service.run_view(old)
            await self.service.assert_desktop_idle(db, ignore_agent_run=agent_run_id)
            r = Playback(
                id=uuid.uuid4(),
                tenant_id=w.tenant_id,
                owner_id=user.id,
                workflow_id=w.id,
                version_id=version_id,
                agent_run_id=agent_run_id,
                request_id=request_id,
                fingerprint=fingerprint,
                status="running",
                script=script.model_dump(),
                digest=script.digest(),
                input_summary={k: "••••••" if k in script.secret_parameters else v for k, v in inputs.items()},
                progress=0,
                result={},
            )
            if agent_run_id:
                actor = await db.get(AgentRun, agent_run_id)
                if actor is None or actor.tenant_id != w.tenant_id or not actor.lane_held:
                    fail(403, "The Agent Run no longer owns its execution lane")
                held = (
                    (
                        await db.execute(
                            select(AgentRun.id)
                            .where(AgentRun.tenant_id == w.tenant_id, AgentRun.lane_held.is_(True))
                            .limit(257)
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(held) > 256:
                    fail(409, "Too many active desktop task identities")
                self.service.driver.runtime_contexts["play_" + r.id.hex] = {
                    "tenant_id": str(actor.tenant_id),
                    "run_id": str(actor.id),
                    "agent_id": str(actor.agent_id),
                    "active_run_ids": [str(i) for i in held],
                }
            # Provider claim is the physical desktop authority. A DB reservation
            # alone must not publish a running operation on an occupied desktop.
            try:
                await self.service.driver.frame("play_" + r.id.hex)
            except DriverFailure as exc:
                fail(409, str(exc))
            db.add(r)
            await db.commit()
            task = asyncio.create_task(self._execute(r.id, inputs))
            self.service.tasks[r.id] = task
            task.add_done_callback(lambda _: self.service.tasks.pop(r.id, None))
            return self.service.run_view(r)

    async def _execute(self, ident: uuid.UUID, inputs: dict[str, str]) -> None:
        s = self.service
        started = time.monotonic()
        session = "play_" + ident.hex
        checks = []
        reconciled = []
        status, error, step_number = "succeeded", "", 0
        try:
            async with asyncio.timeout(180):
                async with async_session() as db:
                    r = await db.get(Playback, ident)
                    if r is None:
                        raise RuntimeError("Playback reservation disappeared")
                    script = Script.model_validate(r.script)
                for index, step in enumerate(script.steps):
                    step_number = index + 1
                    async with async_session() as db:
                        r = await db.get(Playback, ident)
                        actor_ended = False
                        if r is not None and r.agent_run_id:
                            actor = await db.get(AgentRun, r.agent_run_id)
                            actor_ended = actor is None or not actor.lane_held
                        if r is None or r.cancel_requested or actor_ended:
                            status = "cancelled"
                            break
                    next_check = (
                        script.steps[index + 1]
                        if index + 1 < len(script.steps) and script.steps[index + 1].action == "assert_text"
                        else None
                    )
                    if step.action != "assert_text" and next_check is not None:
                        try:
                            async with s.lock:
                                await s.driver.execute(
                                    session, next_check, inputs, f"{ident.hex}_{index}_precheck", s.applications
                                )
                        except DriverFailure as exc:
                            if not exc.condition_absent:
                                raise
                        else:
                            raise DriverFailure(
                                "The following result check already passes before input. Reset or inspect the business state so a new write can be distinguished."
                            )
                    deadline = time.monotonic() + step.timeout_seconds
                    while True:
                        try:
                            async with s.lock:
                                await s.driver.execute(session, step, inputs, f"{ident.hex}_{index}", s.applications)
                            if step.action == "assert_text":
                                checks.append({"step": index + 1, "passed": True})
                            break
                        except DriverFailure as exc:
                            if exc.uncertain and next_check is not None:
                                # No input retry: only an explicitly recorded,
                                # previously absent postcondition can reconcile it.
                                recovery_deadline = time.monotonic() + next_check.timeout_seconds
                                recovered = False
                                while time.monotonic() < recovery_deadline:
                                    try:
                                        async with s.lock:
                                            await s.driver.execute(
                                                session,
                                                next_check,
                                                inputs,
                                                f"{ident.hex}_{index}_reconcile",
                                                s.applications,
                                            )
                                        recovered = True
                                        break
                                    except DriverFailure:
                                        await asyncio.sleep(0.3)
                                if recovered:
                                    reconciled.append({"step": index + 1, "verified_by": index + 2})
                                    break
                            if step.action != "assert_text" or exc.uncertain or time.monotonic() >= deadline:
                                raise
                            # Only read-only assertions may poll. Input is sent once.
                            await asyncio.sleep(0.3)
                    async with async_session() as db:
                        r = await db.get(Playback, ident)
                        if r is None:
                            raise RuntimeError("Playback reservation disappeared")
                        r.progress, r.updated_at = index + 1, now()
                        await db.commit()
        except DriverFailure as exc:
            status, error = ("unknown" if exc.uncertain else "failed"), str(exc)
        except (TimeoutError, asyncio.CancelledError):
            status, error = (
                "unknown",
                "Execution deadline or service shutdown interrupted the workflow. Inspect the desktop and business result before retrying.",
            )
        except Exception:
            # Internal details stay out of the model-visible result. The worker
            # retains a precise failed step and never repeats a write.
            import logging

            logging.getLogger(__name__).exception("Desktop playback internal failure: %s", ident)
            status, error = (
                "failed",
                "Desktop execution encountered an internal error; inspect the failed step before retrying.",
            )
        evidence, release_confirmed = False, False
        try:
            async with s.lock:
                frame = await s.driver.frame(session)
                folder = s.config.evidence_dir / str(ident)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "final.png").write_bytes(s.driver.png(frame))
                evidence = True
        except (DriverFailure, OSError, ValueError):
            if status == "succeeded":
                status, error = (
                    "unknown",
                    "Workflow checks passed, but the final evidence could not be stored. Inspect the result before retrying.",
                )
        try:
            async with s.lock:
                await s.driver.release(session)
            release_confirmed = True
        except DriverFailure:
            if status == "succeeded":
                status, error = (
                    "unknown",
                    "Workflow checks passed, but desktop release is unconfirmed. Do not start another operation until reconciled.",
                )
        async with async_session() as db:
            r = await db.get(Playback, ident)
            if r:
                r.status, r.updated_at = status, now()
                r.result = {
                    "checks": checks,
                    "reconciled_input_steps": reconciled,
                    "error": error,
                    "failed_step": step_number if status not in {"succeeded", "cancelled"} else None,
                    "seconds": round(time.monotonic() - started, 3),
                    "evidence": evidence,
                    "release_confirmed": release_confirmed,
                }
                await db.commit()

    async def get(self, db: AsyncSession, user: User, ident: uuid.UUID) -> Playback:
        tenant = self.service.authorize(user)
        r = (
            await db.execute(select(Playback).where(Playback.id == ident, Playback.tenant_id == tenant))
        ).scalar_one_or_none()
        if not r:
            fail(404, "Execution not found")
        await self.service.workflow(db, user, r.workflow_id)
        return r

    async def cancel(self, db: AsyncSession, user: User, ident: uuid.UUID) -> dict:
        r = await self.get(db, user, ident)
        if r.status == "running":
            r.cancel_requested = True
            await db.commit()
        return self.service.run_view(r)

    async def recover(self) -> None:
        """A single worker can identify its own interrupted reservations at startup."""
        async with self.service.lock, async_session() as db:
            rows = (await db.execute(select(Playback).where(Playback.status == "running"))).scalars().all()
            for r in rows:
                released = False
                try:
                    native = "run_" + r.agent_run_id.hex if r.agent_run_id else "play_" + r.id.hex
                    await self.service.driver.release(native)
                    released = True
                except DriverFailure:
                    pass
                r.status, r.updated_at = "unknown", now()
                r.result = {
                    "error": "Service restarted during execution. Inspect business results before retrying.",
                    "release_confirmed": released,
                    "evidence": False,
                }
            await db.commit()

    async def maintenance(self) -> None:
        """The sole feature worker reclaims abandoned manual recording leases."""
        while True:
            await asyncio.sleep(10)
            async with self.service.lock, async_session() as db:
                rows = (
                    (
                        await db.execute(
                            select(Recording)
                            .where(
                                Recording.status.in_(["active", "release_pending"]),
                                Recording.last_seen < now() - timedelta(seconds=90),
                            )
                            .limit(20)
                        )
                    )
                    .scalars()
                    .all()
                )
                for r in rows:
                    try:
                        await self.service.driver.release("record_" + r.id.hex)
                    except DriverFailure:
                        r.status = "release_pending"
                    else:
                        r.status = "expired"
                        self.service.recording_inputs.pop(r.id, None)
                        w = await db.get(Workflow, r.workflow_id)
                        if w and w.revision == r.base_revision:
                            w.draft, w.updated_at = r.script, now()
                            w.revision += 1
                await db.commit()

    async def close(self) -> None:
        tasks = list(self.service.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
