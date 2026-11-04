"""Bounded account-state access to the broker's own Playwright browser.

The persistent context uses a private pipe. Temporary, hidden documents read
and update origin storage without loading business pages or installing scripts.
"""

from __future__ import annotations

import asyncio
import base64
import json
from contextlib import asynccontextmanager, suppress
from typing import Literal, TypedDict
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError

MAX_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT = 4
COOKIE_FIELDS = {"name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires", "partitionKey"}


class StorageSnapshot(TypedDict):
    cookies: list[dict[str, object]]
    origins: dict[str, dict[str, str]]


class ConnectedSnapshot(TypedDict):
    connected: Literal[True]
    browser_id: str
    snapshot: StorageSnapshot


class ClosedSnapshot(TypedDict):
    connected: Literal[False]


def ckey(c):
    return "c:" + json.dumps(
        [c["domain"], c["path"], c["name"], c.get("partitionKey")], sort_keys=True, separators=(",", ":")
    )


def lkey(site, key):
    return "l:" + json.dumps([site, key], separators=(",", ":"))


def origin(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname
    if ":" in host:
        host = "[" + host + "]"
    port = parsed.port
    suffix = f":{port}" if port and port != {"http": 80, "https": 443}[parsed.scheme] else ""
    return parsed.scheme + "://" + host + suffix


class Document:
    """One session-owned hidden target, with bounded legacy CDP messages."""

    def __init__(self, root):
        self.root = root
        self.target = None
        self.creation_started = False
        self.sid = None
        self.serial = 0
        self.pending = {}
        self.tasks = set()
        self.listener = self.receive

    def receive(self, event):
        if event.get("sessionId") != self.sid:
            return
        message = event.get("message", "")
        if len(message.encode()) > 2 * MAX_BYTES:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("Browser storage response exceeds its bound"))
            return
        data = json.loads(message)
        if "id" in data:
            future = self.pending.get(data["id"])
            if future and not future.done():
                if "error" in data:
                    future.set_exception(RuntimeError("Browser storage command was rejected"))
                else:
                    future.set_result(data.get("result", {}))
        elif data.get("method") == "Fetch.requestPaused":
            task = asyncio.create_task(
                self.call(
                    "Fetch.fulfillRequest",
                    {
                        "requestId": data["params"]["requestId"],
                        "responseCode": 200,
                        "responseHeaders": [
                            {"name": "Content-Type", "value": "text/html; charset=utf-8"},
                            {"name": "Cache-Control", "value": "no-store"},
                        ],
                        "body": base64.b64encode(b"<!doctype html><html><body></body></html>").decode(),
                    },
                )
            )
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def call(self, method, params=None):
        self.serial += 1
        ident = self.serial
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                await self.root.send(
                    "Target.sendMessageToTarget",
                    {
                        "sessionId": self.sid,
                        "message": json.dumps({"id": ident, "method": method, "params": params or {}}),
                    },
                )
                return await future
        except (PlaywrightError, TimeoutError) as exc:
            raise RuntimeError("Browser storage operation did not complete: " + method) from exc
        finally:
            self.pending.pop(ident, None)

    async def open(self):
        self.root.on("Target.receivedMessageFromTarget", self.listener)
        self.creation_started = True
        async with asyncio.timeout(REQUEST_TIMEOUT):
            self.target = (await self.root.send("Target.createTarget", {"url": "about:blank", "hidden": True}))[
                "targetId"
            ]
            self.sid = (await self.root.send("Target.attachToTarget", {"targetId": self.target, "flatten": False}))[
                "sessionId"
            ]
        await self.call("DOMStorage.enable")
        await self.call("Page.enable")
        await self.call("Network.setBypassServiceWorker", {"bypass": True})
        await self.call("Network.setCacheDisabled", {"cacheDisabled": True})
        await self.call("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})

    async def storage(self, site, changes):
        await self.call("Page.navigate", {"url": site + "/"})
        for _ in range(80):
            tree = await self.call("Page.getFrameTree")
            if tree["frameTree"]["frame"].get("securityOrigin") == site:
                break
            await asyncio.sleep(0.025)
        else:
            raise RuntimeError("Browser storage origin was not established")
        storage = {"securityOrigin": site, "isLocalStorage": True}
        for key, value in changes.items():
            params = {"storageId": storage, "key": key}
            if value is not None:
                params["value"] = value
            await self.call(
                "DOMStorage.removeDOMStorageItem" if value is None else "DOMStorage.setDOMStorageItem", params
            )
        items = dict((await self.call("DOMStorage.getDOMStorageItems", {"storageId": storage}))["entries"])
        if any(items.get(k) != v for k, v in changes.items()):
            raise RuntimeError("Browser storage write was not confirmed")
        return items

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.root.remove_listener("Target.receivedMessageFromTarget", self.listener)
        if self.target:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                await self.root.send("Target.closeTarget", {"targetId": self.target})


class Browser:
    def __init__(self):
        self.context = None
        self.root = None
        self.instance = ""
        self.origins = set()
        self.lock = asyncio.Lock()
        self.page_listener = self.observe_page

    @property
    def connected(self):
        return self.context is not None and self.context.browser is not None and self.context.browser.is_connected()

    def observe_frame(self, frame):
        site = origin(frame.url)
        if site:
            self.origins.add(site)

    def observe_page(self, page):
        for frame in page.frames:
            self.observe_frame(frame)
        page.on("framenavigated", self.observe_frame)

    async def bind(self, context, identity):
        await self.unbind()
        self.context, self.instance = context, identity
        self.root = await context.browser.new_browser_cdp_session()
        context.on("page", self.page_listener)
        for page in context.pages:
            self.observe_page(page)

    async def unbind(self):
        if self.context:
            self.context.remove_listener("page", self.page_listener)
            for page in self.context.pages:
                page.remove_listener("framenavigated", self.observe_frame)
        if self.root:
            # A closed browser has already destroyed this session and its hidden targets.
            with suppress(PlaywrightError):
                await self.root.detach()
        self.context, self.root = None, None

    async def root_call(self, method, params=None):
        if not self.connected:
            raise RuntimeError("Business browser is closed")
        if self.root is None:
            assert self.context is not None
            self.root = await self.context.browser.new_browser_cdp_session()
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                return await self.root.send(method, params or {})
        except (PlaywrightError, TimeoutError) as exc:
            raise RuntimeError("Browser operation did not complete: " + method) from exc

    @asynccontextmanager
    async def document(self):
        if not self.connected:
            raise RuntimeError("Business browser is closed")
        if self.root is None:
            assert self.context is not None
            self.root = await self.context.browser.new_browser_cdp_session()
        root = self.root
        document = Document(root)
        try:
            await document.open()
            yield document
        finally:
            try:
                await document.close()
                if document.creation_started and document.target is None:
                    async with asyncio.timeout(REQUEST_TIMEOUT):
                        await root.detach()
                    self.root = None
            except (PlaywrightError, RuntimeError, TimeoutError):
                # Detaching the creating session removes even a hidden target
                # whose create/close acknowledgement was lost. Never leave it orphaned.
                with suppress(PlaywrightError):
                    await root.detach()
                self.root = None

    async def snapshot(self, hints=None) -> ConnectedSnapshot | ClosedSnapshot:
        if not self.connected:
            return {"connected": False}
        for site in hints or []:
            if not isinstance(site, str) or origin(site) != site:
                raise RuntimeError("Invalid browser origin hint")
            self.origins.add(site)
        if len(self.origins) > 128:
            raise RuntimeError("Browser exceeds its observed-origin bound")
        cookies = (await self.root_call("Storage.getCookies"))["cookies"]
        if any(c.get("partitionKeyOpaque") for c in cookies):
            raise RuntimeError("Opaque partitioned cookies require a business-system adapter")
        cookies = [{k: v for k, v in c.items() if k in COOKIE_FIELDS} for c in cookies]
        observed = {}
        if self.origins:
            async with self.document() as doc:
                for site in sorted(self.origins):
                    observed[site] = await doc.storage(site, {})
        cookies.sort(key=ckey)
        result: StorageSnapshot = {"cookies": cookies, "origins": observed}
        if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_BYTES:
            raise RuntimeError("Browser state exceeds its synchronization bound")
        return {"connected": True, "browser_id": self.instance, "snapshot": result}

    async def apply(self, desired, expected):
        sites = {json.loads(k[2:])[0] for k in desired if k.startswith("l:")}
        current = await self.snapshot(sites)
        if current["connected"] is False:
            raise RuntimeError("Business browser closed during synchronization")
        if current["snapshot"] != expected:
            raise RuntimeError("Business browser changed during synchronization; retry observation")
        cookies = {ckey(c): c for c in expected["cookies"]}
        added, deleted, storage = [], [], {}
        for key, value in desired.items():
            if key.startswith("c:"):
                if value == cookies.get(key):
                    continue
                if value is None:
                    domain, path, name, partition = json.loads(key[2:])
                    params = {"name": name, "domain": domain, "path": path}
                    if partition:
                        params["partitionKey"] = partition
                    deleted.append(params)
                else:
                    cookie = dict(value)
                    if not cookie["domain"].startswith("."):
                        domain = cookie.pop("domain")
                        cookie["url"] = ("https://" if cookie.get("secure") else "http://") + domain + cookie["path"]
                    if cookie.get("expires", 0) < 0:
                        cookie.pop("expires", None)
                    added.append(cookie)
            elif key.startswith("l:"):
                site, name = json.loads(key[2:])
                if expected["origins"].get(site, {}).get(name) != value:
                    storage.setdefault(site, {})[name] = value
        if added:
            await self.root_call("Storage.setCookies", {"cookies": added})
        if deleted or storage:
            async with self.document() as doc:
                for params in deleted:
                    await doc.call("Network.deleteCookies", params)
                for site, changes in storage.items():
                    await doc.storage(site, changes)
        verified = await self.snapshot(sites)
        if verified["connected"] is False:
            raise RuntimeError("Browser synchronization was not confirmed")
        actual = {ckey(c): c for c in verified["snapshot"]["cookies"]}
        for key, value in desired.items():
            if key.startswith("c:"):
                if actual.get(key) != value:
                    raise RuntimeError("Browser cookie write was not confirmed")
            else:
                site, name = json.loads(key[2:])
                if verified["snapshot"]["origins"].get(site, {}).get(name) != value:
                    raise RuntimeError("Browser storage write was not confirmed")
        return {"ok": True}
