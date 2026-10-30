"""Capability-side identity and lease adapter; no hypervisor access or guest secrets."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import uuid

import httpx

from .driver import DesktopPreparing, DriverFailure


class SandboxGateway:
    def __init__(self, config):
        self.config = config
        self.bindings: dict[str, dict] = {}
        self.inflight: set[str] = set()

    def bind(self, session: str, tenant: uuid.UUID, owner: uuid.UUID, agent: uuid.UUID | None, operation: str):
        scope = {"tenant_id": str(tenant), "owner_id": str(owner), "agent_id": str(agent) if agent else None}
        if session in self.bindings:
            if self.bindings[session]["scope"] != scope or self.bindings[session]["operation"] != operation:
                raise DriverFailure("A desktop session cannot change its account or Agent")
            return
        same = next((x for x in self.bindings.values() if x["operation"] == operation and x["scope"] == scope), None)
        self.bindings[session] = {
            "scope": scope,
            "operation": operation,
            "nonce": same["nonce"] if same else secrets.token_urlsafe(40),
        }

    async def request(self, path: str, payload: dict | None = None, *, query: dict | None = None, method: str = "POST"):
        try:
            async with (
                httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(210, connect=5)) as client,
                client.stream(
                    method,
                    self.config.sandbox_url.rstrip("/") + path,
                    json=payload,
                    params=query,
                    headers={"Authorization": "Bearer " + self.config.sandbox_token},
                ) as response,
            ):
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 12 * 1024 * 1024:
                        raise DriverFailure("Cloud desktop response exceeded 12 MiB", uncertain=True)
            value = json.loads(raw)
            if response.status_code == 425:
                raise DesktopPreparing(str(value.get("detail", "Windows 正在准备，请稍后观察")))
            if response.status_code >= 400:
                raise DriverFailure(
                    str(value.get("detail", "Cloud desktop operation failed"))[:1000],
                    uncertain=response.status_code == 502,
                )
            return value
        except (httpx.HTTPError, ValueError) as exc:
            raise DriverFailure(
                "Cloud desktop connection interrupted; inspect the task before repeating input", uncertain=True
            ) from exc

    async def call(self, session: str, body: dict) -> dict:
        if session not in self.bindings:
            raise DriverFailure("This desktop operation has no authenticated account and Agent scope")
        self.inflight.add(session)
        try:
            return await self.request("/v1/call", {**self.bindings[session], "body": body})
        finally:
            self.inflight.discard(session)

    async def release(self, session: str, body: dict) -> None:
        binding = self.bindings.get(session)
        if not binding:
            return
        if any(k != session and x == binding for k, x in self.bindings.items()):
            self.bindings.pop(session)
            return
        await self.request("/v1/release", {**binding, "body": body})
        self.bindings.pop(session, None)

    async def heartbeat(self):
        from sqlalchemy import select

        from app.database import async_session
        from app.models.agent_run import AgentRun

        from .models import Playback, Recording

        while True:
            await asyncio.sleep(20)
            unique = {x["nonce"]: (session, x) for session, x in self.bindings.items()}
            for session, value in unique.values():
                kind, ident = value["operation"].split("_", 1)
                model = {"run": AgentRun, "play": Playback, "record": Recording}[kind]
                async with async_session() as db:
                    row = (await db.execute(select(model).where(model.id == uuid.UUID(ident)))).scalar_one_or_none()
                    active = bool(
                        row
                        and (
                            row.lane_held
                            if kind == "run"
                            else row.status == ("active" if kind == "record" else "running")
                        )
                    )
                if not active and session not in self.inflight:
                    body = {
                        "jsonrpc": "2.0",
                        "id": "cleanup",
                        "method": "tools/call",
                        "params": {
                            "name": "computer",
                            "arguments": {"action": "release", "params": {}, "session_id": value["operation"]},
                        },
                    }
                    try:
                        await self.request("/v1/release", {**value, "body": body})
                    except DriverFailure:
                        logging.getLogger(__name__).warning(
                            "Ended desktop lease release is unconfirmed; host expiry remains authoritative"
                        )
                    for key in [key for key, bound in self.bindings.items() if bound["nonce"] == value["nonce"]]:
                        self.bindings.pop(key)
                    continue
                try:
                    await self.request("/v1/heartbeat", value)
                except DriverFailure:
                    logging.getLogger(__name__).exception("Cloud desktop heartbeat failed")


class DesktopInventory:
    def __init__(self, service):
        self.service = service

    def gateway(self):
        if not self.service.driver.sandbox:
            from .service import fail

            fail(409, "Personal cloud desktops are not configured")
        return self.service.driver.sandbox

    async def listing(self, db, user):
        from app.models.agent import Agent

        self.service.authorize(user)
        values = await self.gateway().request(
            "/v1/desktops", query={"tenant": str(user.tenant_id), "owner": str(user.id)}, method="GET"
        )
        agents = [uuid.UUID(x["agent_id"]) for x in values if x.get("agent_id")]
        names = {}
        if agents:
            from sqlalchemy import select

            names = dict(
                (
                    await db.execute(
                        select(Agent.id, Agent.name).where(Agent.tenant_id == user.tenant_id, Agent.id.in_(agents))
                    )
                ).all()
            )
        return [
            {
                **x,
                "agent_name": names.get(uuid.UUID(x["agent_id"]), "已归档员工")
                if x.get("agent_id")
                else "个人录制与试运行",
            }
            for x in values
        ]

    async def recording_workflow(self, db, user, ident):
        from .service import fail

        entry = next((x for x in await self.listing(db, user) if x["id"] == str(ident)), None)
        if entry is None:
            fail(404, "Cloud desktop not found")
        value = await self.service.create(
            db,
            user,
            entry["agent_name"][:80] + " · 录制流程",
            "",
            desktop_agent_id=uuid.UUID(entry["agent_id"]) if entry["agent_id"] else None,
        )
        await db.commit()
        return value

    async def action(self, user, ident, action):
        from .service import fail

        self.service.authorize(user)
        values = await self.gateway().request(
            "/v1/desktops", query={"tenant": str(user.tenant_id), "owner": str(user.id)}, method="GET"
        )
        if not any(x["id"] == str(ident) for x in values):
            fail(404, "Cloud desktop not found")
        return await self.gateway().request(
            f"/v1/desktops/{ident}/{action}",
            {
                "tenant_id": str(user.tenant_id),
                "owner_id": str(user.id),
                "agent_id": None,
            },
        )
