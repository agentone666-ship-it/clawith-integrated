"""Real interview execution through native chat intake; human review is a separate fact."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select

from app.models.agent_tool_execution import AgentToolExecution
from app.models.audit import ChatMessage
from app.models.chat_session import ChatSession
from app.schemas.recruitment import ContinueInterview, Resume, Review, StartInterview
from app.services import recruitment as hr
from app.services.agent_runtime.adapter import RuntimeAdapterError, RuntimeCommandIntake
from app.services.agent_runtime.chat_intake import ChatRuntimeIntakeError, enqueue_chat_runtime
from app.services.agent_runtime.contracts import CancelRunCommand
from app.services.agent_runtime.run_state_reader import RunStateReadError, open_run_state_reader
from app.services.chat_session_service import create_direct_session
from app.services.llm.model_resolution import resolve_active_agent_model
from app.services.participant_identity import get_or_create_user_participant
from app.services.quota_guard import AgentExpired, QuotaExceeded, check_agent_expired, check_conversation_quota

TERMINAL = {"completed", "failed", "cancelled"}


async def check_quota(user, agent_id=None):
    try:
        await check_conversation_quota(user.id)
        if agent_id:
            await check_agent_expired(agent_id)
    except (QuotaExceeded, AgentExpired) as exc:
        raise HTTPException(403, exc.message) from exc


def find_interview(row, interview_id):
    item = next((i for i in row.interviews if i["id"] == str(interview_id)), None)
    if item is None:
        raise HTTPException(404, "面试记录不存在")
    return item


async def read_state(db, row, item):
    try:
        async with open_run_state_reader(db) as reader:
            return await reader.get_run_state(row.tenant_id, uuid.UUID(item["run_id"]))
    except RunStateReadError as exc:
        raise HTTPException(503, "暂时无法核实面试执行状态，请稍后重试") from exc


async def require_no_active_interviews(db, row):
    for item in row.interviews:
        if (await read_state(db, row, item)).execution_status not in TERMINAL:
            raise HTTPException(409, "还有面试正在执行或等待处理，请先完成或取消")


async def start(db, user, dossier_id, data: StartInterview):
    await check_quota(user)
    row = await hr.get_dossier(db, user, dossier_id, lock=True)
    # A retried client request returns its existing Run, even after revision advanced.
    if any(i["id"] == str(data.request_id) for i in row.interviews):
        return row
    hr.require_revision(row, data.revision)
    if len(row.interviews) >= 30:
        raise HTTPException(400, "本次招聘已达 30 场面试，请另开一次招聘")
    agent = await hr.require_candidate(db, user, row)
    if agent.status == "creating":
        raise HTTPException(409, "候选员工正在准备工作环境，请稍后重试")
    if row.resume is None or row.candidate_hash != hr.resume_hash(Resume.model_validate(row.resume)):
        raise HTTPException(409, "简历已调整，请先重新组装候选员工")
    await require_no_active_interviews(db, row)
    model = await resolve_active_agent_model(db, agent)
    if model is None:
        raise HTTPException(400, "候选员工没有可用模型，请管理员配置后重试")
    participant = await get_or_create_user_participant(db, user.id, user.display_name or "用户")
    session = await create_direct_session(
        db, tenant_id=row.tenant_id, agent_id=agent.id, user_id=user.id,
        created_by_participant_id=participant.id, title=f"面试 · {data.task.title}"[:200],
    )
    try:
        async with open_run_state_reader(db) as reader:
            intake = await enqueue_chat_runtime(
                db, agent=agent, user=user, session=session, model=model,
                content=data.task.instruction, message_id=data.request_id, run_state_reader=reader,
            )
    except (ChatRuntimeIntakeError, RuntimeAdapterError) as exc:
        raise HTTPException(409, str(exc)) from exc
    if intake is None:
        raise HTTPException(503, "真实执行引擎未启用，请管理员开启 Runtime v2")
    row.interviews = [*row.interviews, {
        "id": str(data.request_id), "candidate_id": str(agent.id), "resume_hash": row.candidate_hash,
        "task": data.task.model_dump(), "run_id": str(intake.handle.run_id), "session_id": str(session.id),
        "decision": None, "feedback": "", "created_at": datetime.now(UTC).isoformat(),
    }]
    row.revision += 1
    if user.role not in ("platform_admin", "org_admin"):
        user.quota_messages_used += 1
    await db.flush()
    await db.refresh(row)
    return row


async def detail(db, user, dossier_id, interview_id):
    row = await hr.get_dossier(db, user, dossier_id)
    item = find_interview(row, interview_id)
    view = await read_state(db, row, item)
    messages = list((await db.execute(select(ChatMessage).where(
        ChatMessage.tenant_id == row.tenant_id,
        ChatMessage.agent_id == uuid.UUID(item["candidate_id"]),
        ChatMessage.conversation_id == item["session_id"],
        ChatMessage.role.in_(["user", "assistant"]),
    ).order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(61))).scalars().all())
    tools = list((await db.execute(select(AgentToolExecution).where(
        AgentToolExecution.tenant_id == row.tenant_id,
        AgentToolExecution.run_id == uuid.UUID(item["run_id"]),
    ).order_by(AgentToolExecution.started_at.desc(), AgentToolExecution.id.desc()).limit(41))).scalars().all())
    return {
        "status": view.execution_status, "summary": (view.result_summary or "")[:12000],
        "error": (view.last_error or "")[:3000], "waiting_reason": (view.waiting_reason or "")[:3000],
        "can_continue": view.execution_status == "waiting_user" and bool(view.waiting_correlation_id),
        "messages": [{"role": m.role, "content": m.content[:4000]} for m in reversed(messages[:60])],
        "tools": [{"id": str(t.id), "name": t.tool_name, "status": t.status,
                   "summary": (t.result_summary or "")[:2000]} for t in reversed(tools[:40])],
        "truncated": len(messages) > 60 or len(tools) > 40 or any(len(m.content) > 4000 for m in messages[:60]),
    }


async def review(db, user, dossier_id, interview_id, data: Review):
    row = await hr.get_dossier(db, user, dossier_id, lock=True)
    hr.require_revision(row, data.revision)
    item = find_interview(row, interview_id)
    view = await read_state(db, row, item)
    if view.execution_status not in TERMINAL:
        raise HTTPException(409, "请等待本场面试结束再给出面评")
    if data.decision == "pass" and view.execution_status != "completed":
        raise HTTPException(400, "本场任务尚未完成，不能标记为通过")
    if item["candidate_id"] != str(row.candidate_id):
        raise HTTPException(409, "这是旧版本的面试记录，请评价当前候选员工")
    if data.decision == "fail" and not data.feedback.strip():
        raise HTTPException(400, "请告诉 HR 哪些地方需要改进")
    row.interviews = [{**i, "decision": data.decision, "feedback": data.feedback,
                       "reviewed_at": datetime.now(UTC).isoformat()} if i["id"] == str(interview_id) else i
                      for i in row.interviews]
    row.revision += 1
    await db.flush()
    await db.refresh(row)
    return row


async def continue_interview(db, user, dossier_id, interview_id, data: ContinueInterview):
    await check_quota(user)
    row = await hr.get_dossier(db, user, dossier_id, lock=True)
    hr.require_revision(row, data.revision)
    item = find_interview(row, interview_id)
    agent = await hr.require_candidate(db, user, row)
    if item["candidate_id"] != str(agent.id):
        raise HTTPException(409, "只能继续当前候选员工的面试")
    view = await read_state(db, row, item)
    if view.execution_status != "waiting_user" or not view.waiting_correlation_id:
        raise HTTPException(409, "当前面试没有等待用户补充内容")
    session = await db.get(ChatSession, uuid.UUID(item["session_id"]))
    model = await resolve_active_agent_model(db, agent)
    if session is None or model is None:
        raise HTTPException(400, "面试会话或可用模型不存在")
    try:
        async with open_run_state_reader(db) as reader:
            intake = await enqueue_chat_runtime(
                db, agent=agent, user=user, session=session, model=model, content=data.content,
                message_id=data.request_id, resume_run_id=uuid.UUID(item["run_id"]),
                resume_correlation_id=view.waiting_correlation_id, run_state_reader=reader,
            )
    except (ChatRuntimeIntakeError, RuntimeAdapterError) as exc:
        raise HTTPException(409, str(exc)) from exc
    if intake is None:
        raise HTTPException(503, "真实执行引擎未启用")
    row.revision += 1
    if user.role not in ("platform_admin", "org_admin"):
        user.quota_messages_used += 1
    await db.flush()
    await db.refresh(row)
    return row


async def cancel(db, user, dossier_id, interview_id, revision):
    row = await hr.get_dossier(db, user, dossier_id, lock=True)
    hr.require_revision(row, revision)
    item = find_interview(row, interview_id)
    if (await read_state(db, row, item)).execution_status in TERMINAL:
        return row
    try:
        await RuntimeCommandIntake(db).cancel_run(CancelRunCommand(
            tenant_id=row.tenant_id, run_id=uuid.UUID(item["run_id"]),
            idempotency_key=f"recruitment-cancel:{item['id']}", actor_user_id=user.id,
            reason="用户结束本场面试",
        ))
    except RuntimeAdapterError as exc:
        raise HTTPException(409, str(exc)) from exc
    row.revision += 1
    await db.flush()
    await db.refresh(row)
    return row
