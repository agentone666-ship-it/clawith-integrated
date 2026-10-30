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
from app.models.tool import AgentTool, Tool
from app.models.user import User

from .code_contracts import CodePlan, PythonScript, load_script
from .contracts import Script
from .driver import DesktopPreparing, DriverFailure
from .models import Playback, Recording, Workflow, now
from .python_compiler import CompilationError, PythonCompiler
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
            v = await self.service.version(db, user, workflow_id, version_id) if version_id else None
            actor = None
            script = load_script(v.script if v else w.draft)
            if isinstance(script, Script) and (
                not script.steps or not any(s.action == "assert_text" for s in script.steps)
            ):
                fail(422, "Record steps and add a result verification before testing")
            script.validate_inputs(inputs)
            if isinstance(script, Script) and any(
                step.action == "assert_text" and step.text.startswith("__PROBE_") for step in script.steps
            ):
                fail(422, "不要使用必定失败的 PROBE 断言暂停流程；请用 observe 检查界面，诊断流程应正常结束。")
            if agent_run_id:
                actor = await db.get(AgentRun, agent_run_id)
                if actor is None or actor.tenant_id != w.tenant_id or not actor.lane_held:
                    fail(403, "The Agent Run no longer owns its execution lane")
                tool_id = v.tool_id if v else uuid.uuid5(w.tenant_id, "desktop-automation-registry")
                assigned = (
                    await db.execute(
                        select(AgentTool.id)
                        .join(Tool, Tool.id == AgentTool.tool_id)
                        .where(
                            AgentTool.agent_id == actor.agent_id,
                            AgentTool.tool_id == tool_id,
                            AgentTool.enabled.is_(True),
                            Tool.enabled.is_(True),
                            Tool.tenant_id == w.tenant_id,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if not assigned:
                    fail(403, "This Agent Run has no assigned automation Tool")
                if self.service.config.sandbox_url:
                    origin = await db.get(User, actor.origin_user_id) if actor.origin_user_id else None
                    if origin is None or not origin.is_active or origin.tenant_id != actor.tenant_id:
                        fail(403, "Desktop invocation requires an active origin account")
                if not version_id and actor.origin_user_id != user.id:
                    fail(403, "Draft tests require the Runtime origin user")
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
                expected_owner = actor.origin_user_id if actor is not None else user.id
                if old.owner_id != expected_owner or old.fingerprint != fingerprint:
                    fail(409, "Request ID was already used for another operation")
                return self.service.run_view(old)
            await self.service.assert_desktop_idle(db, ignore_agent_run=agent_run_id)
            r = Playback(
                id=uuid.uuid4(),
                tenant_id=w.tenant_id,
                owner_id=actor.origin_user_id if actor is not None else user.id,
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
            if isinstance(script, PythonScript):
                try:
                    plan, diagnostics = await PythonCompiler(self.service.config).compile(script, inputs)
                    probe = next(
                        (
                            step
                            for step in plan.steps
                            if step.action == "assert_text" and step.text.startswith("__PROBE_")
                        ),
                        None,
                    )
                    if probe is not None:
                        raise CompilationError(
                            {
                                "code": "invalid_probe_assertion",
                                "message": "不要使用必定失败的 PROBE 断言暂停流程；请用 observe 检查界面，诊断流程应正常结束。",
                                "line": plan.source_lines.get(probe.id),
                            }
                        )
                    if v and diagnostics["compiler_fingerprint"] != v.compiler_fingerprint:
                        raise CompilationError(
                            {"code": "compiler_changed", "message": "Python SDK 环境已改变，请重新测试并发布新版本"}
                        )
                    r.result = {**diagnostics, "compiled_plan": plan.model_dump(), "total_steps": len(plan.steps)}
                except CompilationError as exc:
                    r.status = "failed"
                    r.result = {
                        "error": str(exc),
                        "diagnostic": exc.diagnostic,
                        "desktop_started": False,
                        "evidence": False,
                        "release_confirmed": True,
                    }
                    db.add(r)
                    await db.commit()
                    return self.service.run_view(r)
            if actor is not None:
                await db.refresh(actor)
                if not actor.lane_held:
                    fail(403, "Agent Run ended before desktop execution")
                held = await self.service.desktop_active_runs(db, actor)
                self.service.driver.runtime_contexts["play_" + r.id.hex] = {
                    "tenant_id": str(actor.tenant_id),
                    "run_id": str(actor.id),
                    "agent_id": str(actor.agent_id),
                    "active_run_ids": [str(i) for i in held],
                }
            self.service.bind_desktop("play_" + r.id.hex, user, w.desktop_agent_id, actor)
            # Provider claim is the physical desktop authority. A DB reservation
            # alone must not publish a running operation on an occupied desktop.
            try:
                initial_frame = await self.service.driver.frame("play_" + r.id.hex)
                from .live import store

                store(self.service, r.id, initial_frame)
            except DesktopPreparing as exc:
                await self.service.driver.release("play_" + r.id.hex)
                fail(425, str(exc))
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
        steps, literal = [], False
        from .live import pump

        sampler = asyncio.create_task(pump(s, ident, session))
        try:
            async with asyncio.timeout(180):
                async with async_session() as db:
                    r = await db.get(Playback, ident)
                    if r is None:
                        raise RuntimeError("Playback reservation disappeared")
                    script = load_script(r.script)
                    literal = isinstance(script, PythonScript)
                    if isinstance(script, PythonScript):
                        plan = CodePlan.model_validate(r.result["compiled_plan"])
                        steps = plan.execution_steps(inputs)
                    else:
                        steps = script.steps
                for index, step in enumerate(steps):
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
                        steps[index + 1]
                        if index + 1 < len(steps) and steps[index + 1].action == "assert_text"
                        else None
                    )
                    # Only the final verification suffix guards the preceding
                    # input as a completed operation. Intermediate UI states may
                    # already hold after an earlier read/lookup.
                    transition_check = next_check is not None and all(
                        item.action == "assert_text" for item in steps[index + 1 :]
                    )
                    if step.action != "assert_text" and transition_check and next_check is not None:
                        try:
                            async with s.lock:
                                await s.driver.execute(
                                    session,
                                    next_check,
                                    inputs,
                                    f"{ident.hex}_{index}_precheck",
                                    s.applications_for(session),
                                    literal=literal,
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
                                await s.driver.execute(
                                    session,
                                    step,
                                    inputs,
                                    f"{ident.hex}_{index}",
                                    s.applications_for(session),
                                    literal=literal,
                                )
                            if step.action == "assert_text":
                                checks.append({"step": index + 1, "passed": True})
                            break
                        except DriverFailure as exc:
                            if exc.uncertain and transition_check and next_check is not None:
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
                                                s.applications_for(session),
                                                literal=literal,
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
                        from .trace import capture

                        async with s.lock:
                            r.result = await capture(s, ident, session, index, len(steps), step, r.result or {})
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
        sampler.cancel()
        outcomes = await asyncio.gather(sampler, return_exceptions=True)
        if isinstance(outcomes[0], Exception):
            import logging

            logging.getLogger(__name__).error(
                "Desktop live sampler failed for %s: %s", ident, type(outcomes[0]).__name__
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
                previous = r.result or {}
                source_lines = previous.get("compiled_plan", {}).get("source_lines", {})
                failed_line = source_lines.get(steps[step_number - 1].id) if step_number and literal else None
                r.result = {
                    **previous,
                    "failed_source_line": failed_line if status not in {"succeeded", "cancelled"} else None,
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
        if not r or r.owner_id != user.id:
            fail(404, "Execution not found")
        if await db.get(Workflow, r.workflow_id) is None:
            fail(404, "Execution workflow not found")
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
                    # A restarted gateway has lost its nonce; only host expiry
                    # can settle that old lease. Never claim an unbound release.
                    managed = bool(self.service.config.sandbox_url) and (
                        not r.agent_run_id or str(r.agent_run_id) not in self.service.config.legacy_run_ids
                    )
                    if not managed:
                        await self.service.driver.release(native)
                        released = True
                except DriverFailure:
                    pass
                r.status, r.updated_at = "unknown", now()
                r.result = {
                    **(r.result or {}),
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
