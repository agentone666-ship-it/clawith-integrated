"""Host-owned periodic sync; desktop identity, never guest input, selects the account."""

from __future__ import annotations

import asyncio
import json
import re

import httpx
from cryptography.exceptions import InvalidTag

from .browser_state import MAX_BYTES, BrowserStateError, BrowserStates, flatten


class BrowserSync:
    def __init__(self, manager, key_path):
        self.manager = manager
        self.vault = BrowserStates(manager.db, key_path)
        self.desktops: dict[str, asyncio.Lock] = {}
        self.accounts: dict[tuple[str, str], asyncio.Lock] = {}

    async def request(self, row, path, payload=None):
        async with (
            httpx.AsyncClient(trust_env=False, timeout=8) as client,
            client.stream(
                "POST" if payload is not None else "GET",
                "http://" + row["ip"] + ":8090/browser/" + path,
                headers={"Authorization": "Bearer " + row["token"]},
                json=payload,
            ) as response,
        ):
            response.raise_for_status()
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_BYTES + 65536:
                    raise BrowserStateError("Browser response exceeds its synchronization bound")
            return json.loads(raw)

    async def once(self, ident):
        lifecycle = self.manager.locks.get(ident)
        if lifecycle and lifecycle.locked():
            return
        await self.synchronize(ident)

    async def synchronize(self, ident):
        # Own browser transactions independently; never delay ordinary pointer/key input.
        async with self.desktops.setdefault(ident, asyncio.Lock()):
            await self._synchronize(ident)

    async def _synchronize(self, ident):
        row = self.manager.row(ident)
        if row["state"] != "ready":
            return
        async with self.accounts.setdefault((row["tenant"], row["owner"]), asyncio.Lock()):
            try:
                canonical = self.vault.state(row)[0]
                hints = sorted({json.loads(k[2:])[0] for k in canonical if k.startswith("l:")})
                result = await self.request(row, "snapshot", {"origins": hints})
                if not result.get("connected"):
                    self.vault.status(ident, "waiting")
                    return
                epoch = result.get("browser_id", "")
                if not isinstance(epoch, str) or not re.fullmatch("[a-f0-9]{64}", epoch):
                    raise BrowserStateError("Business browser identity is unavailable")
                snapshot = result["snapshot"]
                flatten(snapshot)
                desired = self.vault.prepare(row, snapshot, epoch)
                applied = await self.request(row, "apply", {"state": desired, "expected": snapshot})
                if applied != {"ok": True}:
                    raise BrowserStateError("Browser did not acknowledge synchronization")
                self.vault.acknowledge(row, desired, self.manager.clock())
            except (httpx.HTTPError, BrowserStateError, ValueError, KeyError, InvalidTag, TimeoutError):
                # Credentials and guest response bodies are deliberately excluded.
                self.vault.status(ident, "error")

    async def run(self):
        while True:
            rows = self.manager.db.execute("SELECT id FROM desktops WHERE state='ready' LIMIT 10").fetchall()
            await asyncio.gather(*(self.once(row[0]) for row in rows))
            await asyncio.sleep(3)
