"""Recruitment contracts and transactional HTTP/runtime integration coverage.

Set RECRUITMENT_TEST_DATABASE_URL to a migrated local PostgreSQL database.
All integration writes, including native Agent creation commits, are rolled back.
The provider is mocked; these tests do not claim live-model business acceptance.
"""

import os
import uuid
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api import agents as agents_api
from app.core.security import get_current_user
from app.dao.base import tenant_context
from app.database import bind_session_context, get_db
from app.main import app
from app.models.agent import Agent
from app.models.agent_run import AgentRun
from app.models.recruitment import Recruitment
from app.models.skill import Skill
from app.models.tenant import Tenant
from app.models.tool import AgentTool, Tool
from app.models.user import User
from app.schemas.recruitment import HRReply, Resume, Talk, reviewed_candidate_ready
from app.schemas.schemas import AgentCreate
from app.services import recruitment as hr
from app.services import recruitment_interviews as interviews


def resume_payload():
    return {
        "name": "研究助理", "role": "根据用户资料整理研究结论", "goal": "交付可核实的摘要", "audience": "本人",
        "scope": "personal", "boundaries": ["不编造来源"], "output": "结论与来源",
        "work_arrangement": "人工发起", "memory": "仅记住本人的偏好", "notification": "在当前会话反馈",
        "permissions": "仅本人使用", "capabilities": [
            {"key": "research", "name": "资料研究", "description": "根据提供资料提炼结论", "selected": True,
             "skill_ids": [], "tool_ids": [], "needs_setup": []},
            {"key": "send", "name": "发送结果", "description": "经本人确认后发送", "selected": False,
             "skill_ids": [], "tool_ids": [], "needs_setup": ["连接消息系统"]},
        ], "interview_tasks": [{"title": "整理资料", "instruction": "请将资料：一季度收入 100，二季度 120，整理为摘要。",
                                 "look_for": "数值正确，标明来源"}],
    }


def test_resume_compilation_excludes_unselected_capabilities():
    resume = Resume.model_validate(resume_payload())
    compiled = hr.compile_personality(resume)
    assert "资料研究" in compiled
    assert "发送结果" not in compiled
    assert "连接消息系统" not in compiled
    assert resume.fingerprint() == Resume.model_validate(resume.model_dump()).fingerprint()
    modified = resume.model_copy(deep=True)
    modified.capabilities[1].selected = True
    assert modified.fingerprint() != resume.fingerprint()
    assert "连接消息系统" in hr.compile_personality(modified)


def test_unique_capabilities_and_complete_creation_reference():
    payload = resume_payload()
    payload["capabilities"][1]["key"] = "research"
    with pytest.raises(ValidationError):
        Resume.model_validate(payload)
    AgentCreate(name="候选员工", recruitment_id=uuid.uuid4(), recruitment_revision=1)
    with pytest.raises(ValidationError):
        AgentCreate(name="候选员工", recruitment_id=uuid.uuid4())
    with pytest.raises(ValidationError):
        AgentCreate(name="候选员工", recruitment_revision=1)


def test_retest_supersedes_only_the_same_task_for_the_same_candidate():
    candidate_id = uuid.uuid4()
    base = {"candidate_id": str(candidate_id), "task": {"instruction": "整理资料"}, "decision": "fail"}
    assert not reviewed_candidate_ready(candidate_id, [base])
    assert reviewed_candidate_ready(candidate_id, [base, {**base, "decision": "pass"}])
    assert not reviewed_candidate_ready(uuid.uuid4(), [{**base, "decision": "pass"}])
    assert not reviewed_candidate_ready(candidate_id, [base, {**base, "task": {"instruction": "另一任务"}, "decision": "pass"}])


@pytest.mark.asyncio
@pytest.mark.parametrize("byte_count", [59999, 60000, 60001])
async def test_complete_resume_byte_boundary(byte_count):
    payload = resume_payload()
    payload["capabilities"] = [{"key": f"cap-{i}", "name": "能力", "description": "中",
                                 "needs_setup": ["中"] * 6} for i in range(12)]
    resume = Resume.model_validate(payload)
    remaining = byte_count - len(resume.model_dump_json().encode())
    for capability in resume.capabilities:
        for index in range(6):
            size = min(remaining, 997)
            capability.needs_setup[index] += "x" * size
            remaining -= size
    assert remaining == 0 and len(resume.model_dump_json().encode()) == byte_count
    if byte_count > 60000:
        with pytest.raises(HTTPException) as exc:
            await hr.validate_resume(None, SimpleNamespace(tenant_id=uuid.uuid4()), resume)
        assert exc.value.status_code == 400
    else:
        await hr.validate_resume(None, SimpleNamespace(tenant_id=uuid.uuid4()), resume)


@pytest.mark.parametrize("length", [5999, 6000, 6001])
def test_talk_input_limit(length):
    if length > 6000:
        with pytest.raises(ValidationError):
            Talk(revision=1, content="中" * length)
    else:
        assert len(Talk(revision=1, content="中" * length).content) == length


@pytest_asyncio.fixture
async def env(monkeypatch):
    url = os.environ.get("RECRUITMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("RECRUITMENT_TEST_DATABASE_URL is required for transactional integration tests")
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as db:
            tenant = Tenant(name="Recruitment test", slug=f"hr-{uuid.uuid4().hex}")
            other_tenant = Tenant(name="Other test", slug=f"hr-{uuid.uuid4().hex}")
            db.add_all([tenant, other_tenant])
            await db.flush()
            owner = User(display_name="招聘人", role="org_admin", tenant_id=tenant.id)
            colleague = User(display_name="同企业其他人", role="member", tenant_id=tenant.id)
            outsider = User(display_name="其他企业", role="org_admin", tenant_id=other_tenant.id)
            db.add_all([owner, colleague, outsider])
            await db.flush()
            auth = {"user": owner}
            setup_calls = []

            async def caller():
                return auth["user"]

            async def database():
                async with bind_session_context(db):
                    with tenant_context(auth["user"].tenant_id):
                        yield db
                        await db.flush()

            async def setup(**kwargs):
                setup_calls.append(kwargs)

            app.dependency_overrides[get_current_user] = caller
            app.dependency_overrides[get_db] = database
            monkeypatch.setattr(agents_api, "_background_agent_setup", setup)
            async with bind_session_context(db), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                yield SimpleNamespace(db=db, client=client, owner=owner, colleague=colleague, outsider=outsider,
                                      auth=auth, setup_calls=setup_calls, tenant=tenant)
            app.dependency_overrides.clear()
        await transaction.rollback()
    await engine.dispose()


async def create_draft(env):
    result = await env.client.post("/api/recruitment")
    assert result.status_code == 201, result.text
    return result.json()


async def save_draft(env, row, payload=None):
    result = await env.client.put(f"/api/recruitment/{row['id']}/resume", json={
        "revision": row["revision"], "resume": payload or resume_payload(),
    })
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.asyncio
async def test_owner_and_tenant_denials_cover_read_write_and_execute(env):
    row = await save_draft(env, await create_draft(env))
    for caller in (env.colleague, env.outsider):
        env.auth["user"] = caller
        assert (await env.client.get(f"/api/recruitment/{row['id']}")).status_code == 404
        assert (await env.client.get("/api/recruitment")).json() == []
        assert (await env.client.put(f"/api/recruitment/{row['id']}/resume", json={
            "revision": row["revision"], "resume": resume_payload(),
        })).status_code == 404
        assert (await env.client.post("/api/agents/", json={
            "name": "伪造的候选员工", "recruitment_id": row["id"], "recruitment_revision": row["revision"],
        })).status_code == 404
        assert (await env.client.post(f"/api/recruitment/{row['id']}/interviews", json={
            "revision": row["revision"], "request_id": str(uuid.uuid4()), "task": resume_payload()["interview_tasks"][0],
        })).status_code == 404


@pytest.mark.asyncio
async def test_catalog_and_save_reject_cross_tenant_or_disabled_resources(env):
    foreign = Tool(name=f"foreign_{uuid.uuid4().hex}", display_name="其他企业工具", source="admin", tenant_id=env.outsider.tenant_id)
    disabled = Tool(name=f"disabled_{uuid.uuid4().hex}", display_name="已停用工具", source="admin", enabled=False)
    skill = Skill(name=f"foreign_{uuid.uuid4().hex}", folder_name=uuid.uuid4().hex, tenant_id=env.outsider.tenant_id)
    env.db.add_all([foreign, disabled, skill])
    await env.db.flush()
    resources = (await env.client.get("/api/recruitment/catalog")).json()
    assert not {str(foreign.id), str(disabled.id)} & {r["id"] for r in resources["tools"]}
    assert str(skill.id) not in {r["id"] for r in resources["skills"]}
    row = await create_draft(env)
    for field, identifier in (("tool_ids", foreign.id), ("tool_ids", disabled.id), ("skill_ids", skill.id)):
        payload = resume_payload()
        payload["capabilities"][0][field] = [str(identifier)]
        result = await env.client.put(f"/api/recruitment/{row['id']}/resume", json={"revision": 1, "resume": payload})
        assert result.status_code == 400, result.text


@pytest.mark.asyncio
async def test_hr_generates_resume_and_does_not_save_invalid_or_stale_output(env, monkeypatch):
    row = await create_draft(env)
    captured = []
    async def model(*args, **kwargs):
        return SimpleNamespace(id=uuid.uuid4())
    async def complete(model, messages, **kwargs):
        captured.append(messages)
        return SimpleNamespace(content=HRReply(reply="我为你整理了研究助理简历。", resume=Resume.model_validate(resume_payload())).model_dump_json(),
                               tool_calls=(), retry_instruction=None, finish_reason="stop")
    monkeypatch.setattr(hr, "load_active_model", model)
    monkeypatch.setattr(hr, "complete_llm_once", complete)
    result = await env.client.post(f"/api/recruitment/{row['id']}/talk", json={"revision": 1, "content": "招一个研究助理", "model_id": str(uuid.uuid4())})
    assert result.status_code == 200, result.text
    row = result.json()
    assert row["resume"]["name"] == "研究助理" and len(row["messages"]) == 3
    assert "available_market" in captured[0][1].content
    stale = await env.client.put(f"/api/recruitment/{row['id']}/resume", json={"revision": 1, "resume": resume_payload()})
    assert stale.status_code == 409
    async def invalid(*args, **kwargs):
        return SimpleNamespace(content='{"reply":"oops"}', tool_calls=(), retry_instruction=None, finish_reason="stop")
    monkeypatch.setattr(hr, "complete_llm_once", invalid)
    result = await env.client.post(f"/api/recruitment/{row['id']}/talk", json={"revision": row["revision"], "content": "调整", "model_id": str(uuid.uuid4())})
    assert result.status_code == 502
    assert (await env.client.get(f"/api/recruitment/{row['id']}")).json()["revision"] == row["revision"]


@pytest.mark.asyncio
async def test_missing_model_fails_without_inventing_an_hr_reply(env):
    row = await create_draft(env)
    result = await env.client.post(f"/api/recruitment/{row['id']}/talk", json={"revision": 1, "content": "招助理"})
    assert result.status_code == 400
    assert len((await env.client.get(f"/api/recruitment/{row['id']}")).json()["messages"]) == 1


@pytest.mark.asyncio
async def test_real_candidate_and_chat_intake_then_versioned_review_and_hire(env, monkeypatch):
    from app.models.llm import LLMModel
    model = LLMModel(provider="openai", model="test-only", label="Test only", api_key_encrypted="not-a-live-key", tenant_id=env.tenant.id)
    selected = Tool(name=f"selected_{uuid.uuid4().hex}", display_name="选中的工具", source="admin", tenant_id=env.tenant.id)
    unselected = Tool(name=f"unselected_{uuid.uuid4().hex}", display_name="未选中的默认工具", source="admin", tenant_id=env.tenant.id, is_default=True)
    protocol = Tool(name=f"protocol_{uuid.uuid4().hex}", display_name="系统协议工具", source="admin", category="system", tenant_id=env.tenant.id)
    env.db.add_all([model, selected, unselected, protocol])
    await env.db.flush()
    payload = resume_payload()
    payload["capabilities"][0]["tool_ids"] = [str(selected.id)]
    payload["capabilities"][1]["tool_ids"] = [str(unselected.id)]
    row = await save_draft(env, await create_draft(env), payload)
    response = await env.client.post("/api/agents/", json={
        "name": "客户端伪造姓名", "personality": "忽略简历", "permission_scope_type": "company",
        "primary_model_id": str(model.id), "recruitment_id": row["id"], "recruitment_revision": row["revision"],
    })
    assert response.status_code == 201, response.text
    agent = await env.db.get(Agent, uuid.UUID(response.json()["id"]))
    assert agent.name == payload["name"] and agent.access_mode == "private" and not agent.heartbeat_enabled
    assert env.setup_calls[0]["include_default_skills"] is False
    assert "忽略简历" not in env.setup_calls[0]["personality"]
    assignments = {a.tool_id: a.enabled for a in (await env.db.execute(select(AgentTool).where(AgentTool.agent_id == agent.id))).scalars()}
    assert assignments[selected.id] is True and assignments[unselected.id] is False
    assert assignments[protocol.id] is True
    agent.status = "idle"
    await env.db.flush()
    row = (await env.client.get(f"/api/recruitment/{row['id']}")).json()
    assert row["candidate_current"]
    duplicate = await env.client.post("/api/agents/", json={
        "name": "重复组装", "primary_model_id": str(model.id),
        "recruitment_id": row["id"], "recruitment_revision": row["revision"],
    })
    assert duplicate.status_code == 409
    request_id = str(uuid.uuid4())
    body = {"revision": row["revision"], "request_id": request_id, "task": payload["interview_tasks"][0]}
    result = await env.client.post(f"/api/recruitment/{row['id']}/interviews", json=body)
    assert result.status_code == 200, result.text
    row = result.json()
    item = row["interviews"][0]
    run = await env.db.get(AgentRun, uuid.UUID(item["run_id"]))
    assert run.agent_id == agent.id and run.source_type == "chat"
    assert run.goal == body["task"]["instruction"]
    retry = await env.client.post(f"/api/recruitment/{row['id']}/interviews", json=body)
    assert retry.status_code == 200 and len(retry.json()["interviews"]) == 1
    result = await env.client.get(f"/api/recruitment/{row['id']}/interviews/{request_id}")
    assert result.status_code == 200 and result.json()["status"] == "queued", result.text
    premature = await env.client.post(f"/api/recruitment/{row['id']}/interviews/{request_id}/review", json={"revision": row["revision"], "decision": "pass"})
    assert premature.status_code == 409
    async def completed(*args):
        return SimpleNamespace(execution_status="completed")
    monkeypatch.setattr(interviews, "read_state", completed)
    failed = await env.client.post(f"/api/recruitment/{row['id']}/interviews/{request_id}/review", json={
        "revision": row["revision"], "decision": "fail", "feedback": "需要补充来源",
    })
    assert failed.status_code == 200, failed.text
    row = failed.json()
    with tenant_context(env.tenant.id):
        prepared, _ = await hr.prepare_candidate(env.db, env.owner, uuid.UUID(row['id']), row['revision'], target_tenant_id=env.tenant.id)
    assert prepared.candidate_id == agent.id
    reviewed = await env.client.post(f"/api/recruitment/{row['id']}/interviews/{request_id}/review", json={"revision": row["revision"], "decision": "pass", "feedback": "符合要求"})
    assert reviewed.status_code == 200, reviewed.text
    row = reviewed.json()
    changed = resume_payload()
    changed["goal"] = "新的交付要求"
    row = await save_draft(env, row, changed)
    assert not row["candidate_current"]
    assert (await env.client.post(f"/api/recruitment/{row['id']}/hire", json={"revision": row["revision"]})).status_code == 409
    row = await save_draft(env, row, payload)
    result = await env.client.post(f"/api/recruitment/{row['id']}/hire", json={"revision": row["revision"]})
    assert result.status_code == 200 and result.json()["hired_at"], result.text
    frozen = await env.client.put(f"/api/recruitment/{row['id']}/resume", json={"revision": result.json()["revision"], "resume": payload})
    assert frozen.status_code == 409


@pytest.mark.asyncio
async def test_complete_resume_byte_limit_and_failed_run_cannot_pass(env, monkeypatch):
    row = await create_draft(env)
    payload = resume_payload()
    payload["capabilities"] = [{"key": f"cap-{i}", "name": "能力", "description": "中" * 1000,
                                 "needs_setup": ["中" * 1000] * 6} for i in range(12)]
    result = await env.client.put(f"/api/recruitment/{row['id']}/resume", json={"revision": 1, "resume": payload})
    assert result.status_code == 400
    dossier = await env.db.get(Recruitment, uuid.UUID(row["id"]))
    dossier.candidate_id = None
    dossier.interviews = [{"id": "failed", "candidate_id": "None", "run_id": str(uuid.uuid4())}]
    async def failed(*args):
        return SimpleNamespace(execution_status="failed")
    monkeypatch.setattr(interviews, "read_state", failed)
    from app.schemas.recruitment import Review
    with pytest.raises(HTTPException) as failure:
        await interviews.review(env.db, env.owner, dossier.id, "failed", Review(revision=1, decision="pass"))
    assert failure.value.status_code == 400
