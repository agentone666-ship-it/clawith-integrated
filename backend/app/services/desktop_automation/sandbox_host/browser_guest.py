"""Managed Edge CDP adapter, running only inside the interactive Windows guest.

No arbitrary CDP endpoint is exposed. The bridge offers bounded snapshot/apply
operations authenticated by the existing per-desktop secret.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from contextlib import suppress
from urllib.request import ProxyHandler, build_opener

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

MAX_BYTES = 2 * 1024 * 1024
COOKIE_FIELDS = {"name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires", "partitionKey"}


def ckey(c):
    return "c:" + json.dumps(
        [c["domain"], c["path"], c["name"], c.get("partitionKey")], sort_keys=True, separators=(",", ":")
    )


def lkey(site, key):
    return "l:" + json.dumps([site, key], separators=(",", ":"))


class Browser:
    def __init__(self, endpoint="http://127.0.0.1:9222/json/version"):
        self.endpoint = endpoint
        self.ws = None
        self.pending = {}
        self.serial = 0
        self.sessions = {}
        self.hidden = set()
        self.origins = {}
        self.worker = None
        self.tasks = set()
        self.lock = asyncio.Lock()
        self.connected = False
        self.instance = ""

    async def start(self):
        self.worker = asyncio.create_task(self.maintain())

    async def stop(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        if self.ws:
            await self.ws.close()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def call(self, method, params=None, sid=None):
        if not self.ws or len(self.pending) >= 128:
            raise RuntimeError("Business browser is disconnected or busy")
        self.serial += 1
        ident = self.serial
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        try:
            body = {"id": ident, "method": method, "params": params or {}}
            if sid:
                body["sessionId"] = sid
            await self.ws.send(json.dumps(body))
            return await asyncio.wait_for(future, 4)
        finally:
            self.pending.pop(ident, None)

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        return task

    async def read(self):
        ws = self.ws
        if ws is None:
            raise RuntimeError("Business browser is disconnected")
        async for raw in ws:
            msg = json.loads(raw)
            if "id" in msg:
                future = self.pending.get(msg["id"])
                if future and not future.done():
                    if "error" in msg:
                        future.set_exception(RuntimeError("Business browser operation failed"))
                    else:
                        future.set_result(msg.get("result", {}))
            elif msg.get("method") == "Target.attachedToTarget":
                p = msg["params"]
                if p["targetInfo"]["type"] in {"page", "iframe"} and len(self.sessions) < 64:
                    sid = p["sessionId"]
                    self.sessions[sid] = {"script": None, "ready": False, "target": p["targetInfo"]["targetId"]}
                    self.spawn(self.configure(sid))
                else:
                    self.spawn(self.call("Runtime.runIfWaitingForDebugger", sid=p["sessionId"]))
            elif msg.get("method") == "Target.detachedFromTarget":
                self.sessions.pop(msg["params"]["sessionId"], None)
            elif msg.get("method") == "Fetch.requestPaused" and msg.get("sessionId") in self.hidden:
                self.spawn(
                    self.call(
                        "Fetch.fulfillRequest",
                        {
                            "requestId": msg["params"]["requestId"],
                            "responseCode": 200,
                            "responseHeaders": [{"name": "Content-Type", "value": "text/html; charset=utf-8"}],
                            "body": base64.b64encode(b"<!doctype html><html><body></body></html>").decode(),
                        },
                        msg["sessionId"],
                    )
                )
            elif msg.get("method", "").startswith("DOMStorage.domStorage"):
                p = msg["params"]
                store = p.get("storageId", {})
                site = store.get("securityOrigin", "")
                if store.get("isLocalStorage") and site.startswith(("http://", "https://")):
                    items = self.origins.setdefault(site, {})
                    kind = msg["method"]
                    if kind.endswith("ItemsCleared"):
                        items.clear()
                    elif kind.endswith("ItemRemoved"):
                        items.pop(p["key"], None)
                    else:
                        items[p["key"]] = p["newValue"]

    async def configure(self, sid):
        try:
            state = self.sessions[sid]
            await self.call("DOMStorage.enable", sid=sid)
            state["ready"] = True
        finally:
            with suppress(RuntimeError, TimeoutError):
                await self.call("Runtime.runIfWaitingForDebugger", sid=sid)

    async def maintain(self):
        while True:
            reader = None
            try:

                def address():
                    with build_opener(ProxyHandler({})).open(self.endpoint, timeout=1) as response:
                        return json.loads(response.read(65536))["webSocketDebuggerUrl"]

                address_value = await asyncio.to_thread(address)
                # The only permitted debugger is guest loopback; never follow a remote URL.
                if not address_value.startswith("ws://127.0.0.1:") and not address_value.startswith("ws://localhost:"):
                    raise RuntimeError("Invalid business browser endpoint")
                async with connect(address_value, max_size=3 * MAX_BYTES, open_timeout=2, proxy=None) as ws:
                    self.ws = ws
                    self.instance = hashlib.sha256(address_value.encode()).hexdigest()
                    self.sessions.clear()
                    self.origins.clear()
                    self.hidden.clear()
                    reader = asyncio.create_task(self.read())
                    await self.call(
                        "Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True}
                    )
                    self.connected = True
                    await reader
            except (OSError, ValueError, RuntimeError, TimeoutError, WebSocketException):
                pass  # Browser may be closed; status is exposed to the host, without secrets.
            finally:
                self.connected = False
                self.ws = None
                if reader:
                    reader.cancel()
                    await asyncio.gather(reader, return_exceptions=True)
                for future in self.pending.values():
                    if not future.done():
                        future.set_exception(RuntimeError("Business browser disconnected"))
            await asyncio.sleep(1)

    async def snapshot(self) -> dict:
        if not self.connected:
            return {"connected": False}
        cookies = (await self.call("Storage.getCookies"))["cookies"]
        if any(c.get("partitionKeyOpaque") for c in cookies):
            raise RuntimeError("Opaque partitioned cookies require a business-system adapter")
        cookies = [{k: v for k, v in c.items() if k in COOKIE_FIELDS} for c in cookies]
        for sid, state in list(self.sessions.items()):
            if not state["ready"]:
                raise RuntimeError("Business browser tab is still preparing")
            tree = await self.call("Page.getFrameTree", sid=sid)
            state["origins"] = set()
            frames = [tree["frameTree"]]
            while frames:
                frame = frames.pop()
                frames.extend(frame.get("childFrames", []))
                site = frame["frame"].get("securityOrigin", "")
                if site.startswith(("http://", "https://")):
                    state["origins"].add(site)
                    value = await self.call(
                        "DOMStorage.getDOMStorageItems",
                        {"storageId": {"securityOrigin": site, "isLocalStorage": True}},
                        sid,
                    )
                    self.origins[site] = dict(value["entries"])
        cookies.sort(key=ckey)
        result = {"cookies": cookies, "origins": self.origins}
        if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_BYTES:
            raise RuntimeError("Business browser state exceeds synchronization capacity")
        return {"connected": True, "browser_id": self.instance, "snapshot": json.loads(json.dumps(result))}

    async def write_origin(self, site, changes):
        """Restore storage in an invisible, request-intercepted empty document.

        Unlike injecting a saved value on every navigation, this changes the
        real origin database once and cannot resurrect a later app logout.
        No requests or app JavaScript reach the business site.
        """
        target = (await self.call("Target.createTarget", {"url": "about:blank", "hidden": True}))["targetId"]
        sid = None
        try:
            sid = (await self.call("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
            if sid not in self.sessions:
                self.sessions[sid] = {"target": target, "ready": False}
                await self.configure(sid)
            for _ in range(40):
                if self.sessions.get(sid, {}).get("ready"):
                    break
                await asyncio.sleep(0.025)
            else:
                raise RuntimeError("Browser storage context did not become ready")
            self.hidden.add(sid)
            await self.call("Network.setBypassServiceWorker", {"bypass": True}, sid)
            await self.call("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}, sid)
            await self.call("Page.navigate", {"url": site + "/"}, sid)
            for _ in range(40):
                frame = await self.call("Page.getFrameTree", sid=sid)
                if frame["frameTree"]["frame"].get("securityOrigin") == site:
                    break
                await asyncio.sleep(0.025)
            else:
                raise RuntimeError("Browser storage origin was not established")
            storage = {"securityOrigin": site, "isLocalStorage": True}
            for name, value in changes.items():
                p = {"storageId": storage, "key": name}
                if value is not None:
                    p["value"] = value
                await self.call(
                    "DOMStorage.removeDOMStorageItem" if value is None else "DOMStorage.setDOMStorageItem", p, sid
                )
            value = await self.call("DOMStorage.getDOMStorageItems", {"storageId": storage}, sid)
            self.origins[site] = dict(value["entries"])
            if any(self.origins[site].get(k) != v for k, v in changes.items()):
                raise RuntimeError("Browser storage write was not confirmed")
        finally:
            if sid:
                self.hidden.discard(sid)
            if self.connected:
                await self.call("Target.closeTarget", {"targetId": target})

    async def apply(self, desired, expected):
        """Idempotent reconciliation; refuse a changed snapshot before writing."""
        current = await self.snapshot()
        if not current.get("connected") or current["snapshot"] != expected:
            raise RuntimeError("Business browser changed during synchronization; retry observation")
        cookies = {ckey(c): c for c in expected["cookies"]}
        new_cookies = []
        for key, value in desired.items():
            if not key.startswith("c:") or value == cookies.get(key):
                continue
            if value is None:
                domain, path, name, partition = json.loads(key[2:])
                p = {"name": name, "domain": domain, "path": path}
                if partition:
                    p["partitionKey"] = partition
                sid = next(iter(self.sessions), None)
                if not sid:
                    raise RuntimeError("Open the Business Browser before synchronizing cookies")
                await self.call("Network.deleteCookies", p, sid)
            else:
                c = dict(value)
                if c.get("expires", 0) < 0:
                    c.pop("expires", None)
                new_cookies.append(c)
        if new_cookies:
            await self.call("Storage.setCookies", {"cookies": new_cookies})
        sites = {}
        for key, value in desired.items():
            if key.startswith("l:"):
                site, name = json.loads(key[2:])
                if site not in expected["origins"] or expected["origins"][site].get(name) != value:
                    sites.setdefault(site, {})[name] = value
        for site, changes in sites.items():
            await self.write_origin(site, changes)
        verified = await self.snapshot()
        if not verified.get("connected"):
            raise RuntimeError("Business browser synchronization was not confirmed")
        actual = {ckey(c): c for c in verified["snapshot"]["cookies"]}
        for key, value in desired.items():
            if key.startswith("c:"):
                if actual.get(key) != value:
                    raise RuntimeError("Business browser cookie write was not confirmed")
            else:
                site, name = json.loads(key[2:])
                if site in verified["snapshot"]["origins"] and verified["snapshot"]["origins"][site].get(name) != value:
                    raise RuntimeError("Business browser storage write was not confirmed")
        return {"ok": True}
