"""Sole owner of persistent desktop identity, fenced leases and VM reclamation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from .provider import ProviderError

if TYPE_CHECKING:
    from .browser_sync import BrowserSync


class SandboxError(RuntimeError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


class Manager:
    def __init__(self, db: Path, provider, *, idle_seconds: int = 600, lease_seconds: int = 90, max_running: int = 2):
        db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(db)
        db.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS desktops (
            id TEXT PRIMARY KEY, tenant TEXT NOT NULL, owner TEXT NOT NULL, agent TEXT NOT NULL,
            state TEXT NOT NULL, token TEXT NOT NULL, password TEXT NOT NULL,
            personalized INTEGER NOT NULL DEFAULT 0, compute_held INTEGER NOT NULL DEFAULT 0, ip TEXT NOT NULL DEFAULT '',
            created REAL NOT NULL, idle_since REAL NOT NULL, last_error TEXT NOT NULL DEFAULT '', browser_protocol INTEGER NOT NULL DEFAULT 0,
            UNIQUE(tenant,owner,agent));
          CREATE TABLE IF NOT EXISTS leases (
            nonce TEXT PRIMARY KEY, desktop TEXT NOT NULL, operation TEXT NOT NULL,
            state TEXT NOT NULL, heartbeat REAL NOT NULL);
          CREATE INDEX IF NOT EXISTS active_leases ON leases(desktop,state);
        """)
        if "browser_protocol" not in {column[1] for column in self.db.execute("PRAGMA table_info(desktops)")}:
            self.db.execute("ALTER TABLE desktops ADD COLUMN browser_protocol INTEGER NOT NULL DEFAULT 0")
            self.db.commit()
        columns = {column[1] for column in self.db.execute("PRAGMA table_info(desktops)")}
        for name, default in (("vcpus", 2), ("memory_mib", 4096)):
            if name not in columns:
                self.db.execute(f"ALTER TABLE desktops ADD COLUMN {name} INTEGER NOT NULL DEFAULT {default}")
        self.db.commit()
        self.provider = provider
        self.idle_seconds, self.lease_seconds, self.max_running = idle_seconds, lease_seconds, max_running
        self.locks: dict[str, asyncio.Lock] = {}
        self.admission = asyncio.Lock()
        self.startups: dict[str, asyncio.Task] = {}
        self.clock = time.time
        self.browser_sync: BrowserSync | None = None

    def row(self, ident: str):
        value = self.db.execute("SELECT * FROM desktops WHERE id=?", (str(uuid.UUID(ident)),)).fetchone()
        if value is None:
            raise SandboxError("Cloud desktop not found", 404)
        return value

    def create(self, scope: dict) -> str:
        tenant, owner = (str(uuid.UUID(scope[k])) for k in ("tenant_id", "owner_id"))
        agent = str(uuid.UUID(scope["agent_id"])) if scope.get("agent_id") else "studio"
        ident = str(uuid.uuid5(uuid.UUID(tenant), owner + ":" + agent))
        if self.db.execute("SELECT 1 FROM desktops WHERE id=?", (ident,)).fetchone() is None:
            count = self.db.execute(
                "SELECT count(*) FROM desktops WHERE tenant=? AND owner=?", (tenant, owner)
            ).fetchone()[0]
            if count >= 10:
                raise SandboxError("Your account has reached its 10 desktop quota; contact an administrator", 429)
            stamp = self.clock()
            self.db.execute(
                "INSERT INTO desktops(id,tenant,owner,agent,state,token,password,created,idle_since,vcpus,memory_mib) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ident,
                    tenant,
                    owner,
                    agent,
                    "stopped",
                    secrets.token_urlsafe(40),
                    secrets.token_urlsafe(30),
                    stamp,
                    stamp,
                    4,
                    8192,
                ),
            )
            self.db.commit()
        return ident

    def authorize(self, ident: str, tenant: str, owner: str):
        row = self.row(ident)
        if row["tenant"] != str(uuid.UUID(tenant)) or row["owner"] != str(uuid.UUID(owner)):
            raise SandboxError("Cloud desktop not found", 404)
        return row

    def configure_resources(self, ident: str, tenant: str, owner: str, *, vcpus: int, memory_mib: int) -> None:
        """Offline operator only: host service stopped; Windows shut down normally."""
        self.authorize(ident, tenant, owner)
        if self.db.execute("SELECT 1 FROM leases WHERE desktop=? AND state='active' LIMIT 1", (ident,)).fetchone():
            raise SandboxError("An active task owns this desktop; maintenance is not admitted")
        self.provider.set_resources(ident, vcpus=vcpus, memory_mib=memory_mib)
        self.db.execute(
            "UPDATE desktops SET vcpus=?,memory_mib=?,state='stopped',compute_held=0,last_error='' WHERE id=?",
            (vcpus, memory_mib, ident),
        )
        self.db.commit()

    def view(self, row) -> dict:
        lease = self.db.execute(
            "SELECT 1 FROM leases WHERE desktop=? AND state='active' LIMIT 1", (row["id"],)
        ).fetchone()
        return {
            "id": row["id"],
            "agent_id": None if row["agent"] == "studio" else row["agent"],
            "state": row["state"],
            "busy": bool(lease),
            "vcpus": row["vcpus"],
            "memory_mib": row["memory_mib"],
            "persistent": True,
            "compute_held": bool(row["compute_held"]),
            "idle_seconds": max(0, int(self.clock() - row["idle_since"])) if not lease else 0,
            "auto_save_after_seconds": self.idle_seconds,
            "last_error": row["last_error"],
            "browser_sync": self.browser_sync.vault.view(row["id"]) if self.browser_sync else None,
        }

    def listing(self, tenant: str, owner: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM desktops WHERE tenant=? AND owner=? ORDER BY created DESC LIMIT 50",
            (str(uuid.UUID(tenant)), str(uuid.UUID(owner))),
        ).fetchall()
        return [self.view(x) for x in rows]

    def lease(self, ident: str, operation: str, nonce: str) -> None:
        fingerprint = hashlib.sha256(nonce.encode()).hexdigest()
        old = self.db.execute("SELECT * FROM leases WHERE nonce=?", (fingerprint,)).fetchone()
        if old and (
            old["desktop"] != ident
            or old["operation"] != operation
            or old["state"] != "active"
            or old["heartbeat"] < self.clock() - self.lease_seconds
        ):
            raise SandboxError(
                "Desktop lease ended or expired; this operation is fenced. Inspect task state before retrying"
            )
        other = self.db.execute(
            "SELECT nonce FROM leases WHERE desktop=? AND state='active' AND nonce<>? LIMIT 1", (ident, fingerprint)
        ).fetchone()
        if other:
            raise SandboxError("This Agent's desktop is occupied by another task; wait for that task to finish")
        self.db.execute(
            "INSERT INTO leases VALUES(?,?,?,'active',?) ON CONFLICT(nonce) DO UPDATE SET heartbeat=excluded.heartbeat",
            (fingerprint, ident, operation, self.clock()),
        )
        self.db.commit()

    async def ensure(self, ident: str) -> None:
        row = self.row(ident)
        if (
            row["state"] == "ready"
            and (self.browser_sync is None or row["browser_protocol"] == 24)
            and await asyncio.to_thread(self.provider.state, ident) == "running"
        ):
            return
        async with self.admission:
            count = self.db.execute(
                "SELECT count(*) FROM desktops WHERE compute_held=1 AND id<>?",
                (ident,),
            ).fetchone()[0]
            if count >= self.max_running:
                raise SandboxError(
                    "Cloud desktop capacity is currently full; retry after another task releases its desktop", 429
                )
            if shutil.disk_usage(self.provider.root).free < 30 * 1024**3:
                raise SandboxError("Cloud desktop storage reserve is insufficient; contact an administrator", 507)
            self.db.execute(
                "UPDATE desktops SET state=?,compute_held=1,last_error='' WHERE id=?",
                ("restoring" if row["state"] == "saved" else "starting", ident),
            )
            self.db.commit()
        try:
            await asyncio.to_thread(self.provider.start, ident, vcpus=row["vcpus"], memory_mib=row["memory_mib"])
            ip = await asyncio.to_thread(
                self.provider.ready, ident, row["token"], row["password"], bool(row["personalized"])
            )
        except ProviderError as exc:
            self.db.execute("UPDATE desktops SET state='error',last_error=? WHERE id=?", (str(exc)[:400], ident))
            self.db.commit()
            raise SandboxError(str(exc), 503) from exc
        self.db.execute(
            "UPDATE desktops SET state='ready',personalized=1,browser_protocol=24,ip=?,idle_since=? WHERE id=?",
            (ip, self.clock(), ident),
        )
        self.db.commit()
        if self.browser_sync:
            await self.browser_sync.synchronize(ident)

    async def prepare(self, ident: str) -> None:
        async def boot():
            async with self.locks.setdefault(ident, asyncio.Lock()):
                await self.ensure(ident)

        task = self.startups.get(ident)
        if task is None or task.done():
            task = asyncio.create_task(boot())
            self.startups[ident] = task
            task.add_done_callback(lambda result: result.exception() if not result.cancelled() else None)
        try:
            await asyncio.wait_for(asyncio.shield(task), 8)
        except TimeoutError as exc:
            raise SandboxError(
                "Windows 正在准备，尚未发送任何桌面输入。请稍后重新观察画面；no action was dispatched", 425
            ) from exc

    async def call(self, scope: dict, operation: str, nonce: str, body: dict) -> dict:
        ident = self.create(scope)
        self.lease(ident, operation, nonce)
        action = body.get("params", {}).get("arguments", {}).get("action")
        reads = {
            "help",
            "get_desktop_state",
            "get_window_state",
            "get_accessibility_tree",
            "get_screen_size",
            "list_windows",
            "list_apps",
        }
        was_ready = (
            self.row(ident)["state"] == "ready" and await asyncio.to_thread(self.provider.state, ident) == "running"
        )
        await self.prepare(ident)
        if action not in reads and not was_ready:
            raise SandboxError("Windows 已恢复，请先重新观察界面再发送输入；no action was dispatched", 425)
        async with self.locks.setdefault(ident, asyncio.Lock()):
            self.lease(ident, operation, nonce)
            row = self.row(ident)
            try:
                async with (
                    httpx.AsyncClient(trust_env=False, timeout=120 if action == "launch_app" else 45) as client,
                    client.stream(
                        "POST",
                        "http://" + row["ip"] + ":8090/mcp",
                        json=body,
                        headers={"Authorization": "Bearer " + row["token"]},
                    ) as response,
                ):
                    response.raise_for_status()
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 12 * 1024 * 1024:
                            raise SandboxError("Desktop response exceeded its 12 MiB bound", 502)
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise SandboxError("Desktop returned an invalid result", 502)
                if (
                    result.get("result", {}).get("structuredContent", {}).get("business_browser_prepared")
                    and self.browser_sync
                ):
                    for _ in range(3):
                        await self.browser_sync.synchronize(ident)
                        if self.browser_sync.vault.view(ident)["status"] == "synced":
                            break
                        await asyncio.sleep(0.25)
                    if self.browser_sync.vault.view(ident)["status"] != "synced":
                        raise SandboxError(
                            "Business browser opened; account login state is not yet synchronized. Observe before continuing",
                            425,
                        )
                    params = body.get("params", {})
                    arguments = params.get("arguments", {})
                    runtime = (params.get("_meta") or {}).get("io.clawith/runtime")
                    session = "run_" + runtime["run_id"].replace("-", "") if runtime else arguments.get("session_id")
                    async with httpx.AsyncClient(trust_env=False, timeout=40) as client:
                        navigation = await client.post(
                            "http://" + row["ip"] + ":8090/browser/navigate",
                            headers={"Authorization": "Bearer " + row["token"]},
                            json={"session": session, "request_id": arguments.get("request_id")},
                        )
                        navigation.raise_for_status()
                        if navigation.json() != {"ok": True}:
                            raise SandboxError("Business browser navigation was not confirmed; inspect desktop", 502)
                    result["result"]["structuredContent"].pop("business_browser_prepared", None)
                    result["result"]["content"] = [{"type": "text", "text": "Business browser opened."}]
                return result
            except (httpx.HTTPError, ValueError) as exc:
                raise SandboxError(
                    "Desktop connection interrupted; inspect the result before repeating input", 502
                ) from exc
            finally:
                self.db.execute(
                    "UPDATE leases SET heartbeat=? WHERE nonce=? AND state='active'",
                    (self.clock(), hashlib.sha256(nonce.encode()).hexdigest()),
                )
                self.db.commit()

    def heartbeat(self, scope: dict, operation: str, nonce: str) -> None:
        self.lease(self.create(scope), operation, nonce)

    async def release(self, scope: dict, operation: str, nonce: str, body: dict) -> None:
        ident = self.create(scope)
        fingerprint = hashlib.sha256(nonce.encode()).hexdigest()
        pending = self.db.execute("SELECT * FROM leases WHERE nonce=?", (fingerprint,)).fetchone()
        if (
            self.row(ident)["state"] in {"starting", "restoring"}
            and pending
            and pending["state"] == "active"
            and pending["desktop"] == ident
            and pending["operation"] == operation
        ):
            self.db.execute("UPDATE leases SET state='released' WHERE nonce=?", (fingerprint,))
            self.db.execute("UPDATE desktops SET idle_since=? WHERE id=?", (self.clock(), ident))
            self.db.commit()
            return  # Initialization has not admitted any business input.
        async with self.locks.setdefault(ident, asyncio.Lock()):
            fingerprint = hashlib.sha256(nonce.encode()).hexdigest()
            old = self.db.execute("SELECT * FROM leases WHERE nonce=?", (fingerprint,)).fetchone()
            if old is None or old["state"] == "released":
                return
            if old["desktop"] != ident or old["operation"] != operation:
                raise SandboxError("Desktop lease does not belong to this task", 403)
            if old["state"] != "active":
                raise SandboxError("Desktop lease expired; release cannot reclaim a newer task")
            row = self.row(ident)
            if row["state"] == "ready":
                async with httpx.AsyncClient(trust_env=False, timeout=45) as client:
                    response = await client.post(
                        "http://" + row["ip"] + ":8090/mcp",
                        json=body,
                        headers={"Authorization": "Bearer " + row["token"]},
                    )
                    response.raise_for_status()
                    if response.json().get("result", {}).get("isError"):
                        raise SandboxError("Native desktop release remains unconfirmed")
            self.db.execute("UPDATE leases SET state='released' WHERE nonce=?", (fingerprint,))
            self.db.execute("UPDATE desktops SET idle_since=? WHERE id=?", (self.clock(), ident))
            self.db.commit()

    async def suspend(self, ident: str) -> None:
        async with self.locks.setdefault(ident, asyncio.Lock()):
            row = self.row(ident)
            if ident in self.startups and not self.startups[ident].done():
                raise SandboxError("Windows is still preparing; wait before saving")
            if self.db.execute("SELECT 1 FROM leases WHERE desktop=? AND state='active' LIMIT 1", (ident,)).fetchone():
                raise SandboxError("An active task still owns this desktop; stop the task before saving")
            if row["state"] in {"saved", "stopped"}:
                return
            if self.browser_sync and row["state"] == "ready":
                await self.browser_sync.synchronize(ident)
            self.db.execute("UPDATE desktops SET state='saving' WHERE id=?", (ident,))
            self.db.commit()
            try:
                terminal = await asyncio.to_thread(self.provider.save, ident)
            except ProviderError as exc:
                self.db.execute("UPDATE desktops SET state='error',last_error=? WHERE id=?", (str(exc)[:400], ident))
                self.db.commit()
                raise SandboxError(str(exc), 503) from exc
            if terminal not in {"saved", "stopped"}:
                self.db.execute(
                    "UPDATE desktops SET state='error',last_error=? WHERE id=?",
                    ("Provider did not confirm compute release", ident),
                )
                self.db.commit()
                raise SandboxError("Windows provider did not confirm a terminal compute state", 503)
            self.db.execute("UPDATE desktops SET state=?,compute_held=0,last_error='' WHERE id=?", (terminal, ident))
            self.db.commit()

    async def sweep(self) -> None:
        # Expired commands are permanently fenced before reclamation. No force
        # release is sent to a guest; the next task uses a new native identity.
        rows = self.db.execute(
            "SELECT DISTINCT desktop FROM leases WHERE state='active' AND heartbeat<? LIMIT 100",
            (self.clock() - self.lease_seconds,),
        ).fetchall()
        for item in rows:
            ident = item[0]
            if self.locks.setdefault(ident, asyncio.Lock()).locked():
                continue
            self.db.execute(
                "UPDATE leases SET state='expired' WHERE desktop=? AND state='active' AND heartbeat<?",
                (ident, self.clock() - self.lease_seconds),
            )
            self.db.execute("UPDATE desktops SET idle_since=? WHERE id=?", (self.clock(), ident))
        self.db.commit()
        idle = self.db.execute(
            "SELECT id FROM desktops WHERE state IN ('ready','error') AND idle_since<? AND NOT EXISTS(SELECT 1 FROM leases WHERE desktop=desktops.id AND state='active') LIMIT 10",
            (self.clock() - self.idle_seconds,),
        ).fetchall()
        for item in idle:
            await self.suspend(item[0])
        self.db.execute("DELETE FROM leases WHERE state<>'active' AND heartbeat<?", (self.clock() - 7 * 86400,))
        self.db.commit()
