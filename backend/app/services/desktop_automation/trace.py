"""Bounded screenshot timeline owned by playback; observers never reserve a desktop."""

import base64
import math

from sqlalchemy import func, select

from app.models.agent_run import AgentRun
from app.models.agent_tool_execution import AgentToolExecution

from .driver import DriverFailure
from .models import Playback
from .service import fail


async def capture(service, ident, session, index, total, step, previous):
    trace = list(previous.get("trace", []))
    entry = {
        "step": index + 1,
        "action": step.action,
        "app": step.target.app if step.target else "",
        "x": step.x,
        "y": step.y,
    }
    trace.append(entry)
    # Sample at most 32 full frames, with a strict 32 MiB aggregate cap.
    stride = max(1, math.ceil(total / 32))
    if index % stride == 0 and previous.get("trace_bytes", 0) < 32 * 1024 * 1024:
        try:
            frame = await service.driver.frame(session)
            data = service.driver.png(frame)
            if len(data) <= 8 * 1024 * 1024 and previous.get("trace_bytes", 0) + len(data) <= 32 * 1024 * 1024:
                folder = service.config.evidence_dir / str(ident)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"step-{index + 1}.png").write_bytes(data)
                entry["frame"] = True
                previous = {**previous, "trace_bytes": previous.get("trace_bytes", 0) + len(data)}
        except (DriverFailure, OSError, ValueError):
            entry["frame_error"] = "画面暂不可用，步骤结果仍以执行回执为准"
    return {**previous, "trace": trace[-120:]}


async def frame(engine, db, user, ident, step):
    run = await engine.get(db, user, ident)
    if not any(x.get("step") == step and x.get("frame") for x in run.result.get("trace", [])):
        fail(404, "Step frame unavailable")
    path = engine.service.config.evidence_dir / str(run.id) / f"step-{step}.png"
    if not path.is_file():
        fail(404, "Step frame unavailable")
    return {"image": base64.b64encode(path.read_bytes()).decode(), "mime": "image/png"}


async def latest(engine, db, user, agent_id):
    tenant = engine.service.authorize(user)
    query = (
        select(Playback)
        .join(AgentRun, AgentRun.id == Playback.agent_run_id)
        .where(
            Playback.tenant_id == tenant,
            Playback.owner_id == user.id,
            AgentRun.agent_id == agent_id,
        )
        .order_by(Playback.created_at.desc())
        .limit(1)
    )
    run = (await db.execute(query)).scalar_one_or_none()
    if not run:
        return None
    await engine.get(db, user, run.id)
    return engine.service.run_view(run)


async def activity(engine, db, user, agent_id, session_id):
    tenant = engine.service.authorize(user)
    actor = (
        await db.execute(
            select(AgentRun)
            .where(
                AgentRun.tenant_id == tenant,
                AgentRun.origin_user_id == user.id,
                AgentRun.agent_id == agent_id,
                AgentRun.session_id == session_id,
            )
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not actor:
        return None
    count = (
        await db.execute(
            select(func.count())
            .select_from(AgentToolExecution)
            .where(
                AgentToolExecution.run_id == actor.id,
                AgentToolExecution.tenant_id == tenant,
            )
        )
    ).scalar_one()
    run = (
        await db.execute(
            select(Playback)
            .where(
                Playback.tenant_id == tenant,
                Playback.owner_id == user.id,
                Playback.agent_run_id == actor.id,
            )
            .order_by(Playback.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run:
        await engine.get(db, user, run.id)
    return {
        "agent_run_id": str(actor.id),
        "session_id": str(actor.session_id),
        "lane_held": actor.lane_held,
        "tool_calls": count,
        "created_at": actor.created_at.isoformat(),
        "playback": engine.service.run_view(run) if run else None,
        "computer": (engine.service.config.evidence_dir / "computer" / str(actor.id) / "live.png").is_file(),
    }
