"""Real browser processes + shipped guest routes + host sync, without user profiles."""

import ast
import asyncio
import hashlib
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright

from app.services.desktop_automation.sandbox_host.browser_guest import Browser
from app.services.desktop_automation.sandbox_host.browser_sync import BrowserSync
from app.services.desktop_automation.sandbox_host.manager import Manager

BINARY = os.getenv("CLAWITH_TEST_BROWSER")
pytestmark = pytest.mark.skipif(not BINARY, reason="Set CLAWITH_TEST_BROWSER to an installed Chromium/Edge executable")


class Site(BaseHTTPRequestHandler):
    paths: ClassVar[list[str]] = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.paths.append(self.path)
        self.send_response(200)
        script = ""
        if self.path in ["/login", "/rotate"]:
            number = "v1" if self.path == "/login" else "v2"
            self.send_header("Set-Cookie", f"sid={number}; Path=/; HttpOnly; SameSite=Lax")
            script = f"localStorage.setItem('access_token','token-{number}')"
        elif self.path == "/logout":
            self.send_header("Set-Cookie", "sid=; Path=/; HttpOnly; Max-Age=0; SameSite=Lax")
            script = "localStorage.clear();location.replace('/signed-out')"
        received = self.headers.get("Cookie", "")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            ("<html><body><p id='server'>" + received + "</p><script>" + script + "</script></body></html>").encode()
        )


def guest_app(browser, secret):
    import secrets

    app = FastAPI()
    asset = Path(__file__).parents[1] / "app/services/desktop_automation/sandbox_host/windows_bridge.py.in"
    nodes = [
        n
        for n in ast.parse(asset.read_text()).body
        if isinstance(n, ast.AsyncFunctionDef) and n.name in {"browser_snapshot", "browser_apply"}
    ]
    namespace = {
        "app": app,
        "browser": browser,
        "secrets": secrets,
        "TOKEN": secret,
        "Request": Request,
        "JSONResponse": JSONResponse,
        "json": json,
        "asyncio": asyncio,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(asset), "exec"), namespace)  # noqa: S102 -- Shipped HTTP boundary, never model input.
    return app


async def until(fn, predicate, limit=10):
    for _ in range(limit * 10):
        try:
            value = await fn()
        except RuntimeError:
            value = {}
        if predicate(value):
            return value
        await asyncio.sleep(0.1)
    raise AssertionError("Browser condition was not observed")


async def test_real_http_only_login_refresh_logout_cross_account_and_restart(tmp_path, monkeypatch):
    Site.paths.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    site = f"http://localhost:{server.server_port}"
    contexts, browsers = [], []
    api = await async_playwright().start()
    manager = Manager(tmp_path / "private.sqlite", SimpleNamespace(root=tmp_path))
    sync = BrowserSync(manager, tmp_path / "vault.key")
    manager.browser_sync = sync
    rows, guests = [], {}
    client_type = httpx.AsyncClient
    try:
        tenant, owner = str(uuid.uuid4()), str(uuid.uuid4())
        for i in range(3):
            profile = tmp_path / f"profile-{i}"
            context = await api.chromium.launch_persistent_context(
                str(profile),
                executable_path=BINARY,
                headless=True,
                chromium_sandbox=True,
            )
            contexts.append(context)
            browser = Browser()
            browsers.append(browser)
            await browser.bind(context, hashlib.sha256(uuid.uuid4().bytes).hexdigest())
            ident = manager.create(
                {"tenant_id": tenant, "owner_id": owner if i < 2 else str(uuid.uuid4()), "agent_id": str(uuid.uuid4())}
            )
            manager.db.execute("UPDATE desktops SET state='ready',ip=? WHERE id=?", (f"guest-{i}", ident))
            manager.db.commit()
            row = manager.row(ident)
            rows.append(row)
            guests[f"guest-{i}"] = httpx.ASGITransport(app=guest_app(browser, row["token"]))

        async def dispatch(request):
            response = await guests[request.url.host].handle_async_request(request)
            if response.status_code != 200:
                await response.aread()
                print("GUEST_DIAGNOSTIC", request.url.path, response.json().get("error"))
            return response

        monkeypatch.setattr(
            "app.services.desktop_automation.sandbox_host.browser_sync.httpx.AsyncClient",
            lambda **kw: client_type(transport=httpx.MockTransport(dispatch), **kw),
        )

        async def visit(browser, path):
            page = await browser.context.new_page()
            await page.goto(site + path)
            if path == "/logout":
                await page.wait_for_url(site + "/signed-out")
            await page.locator("#server").wait_for(state="attached")
            return {
                "cookie": await page.locator("#server").text_content(),
                "token": await page.local_storage.get_item("access_token"),
            }

        async def synced(index):
            before = {v["targetId"] for v in (await browsers[index].root_call("Target.getTargets"))["targetInfos"]}
            await sync.once(rows[index]["id"])
            after = {v["targetId"] for v in (await browsers[index].root_call("Target.getTargets"))["targetInfos"]}
            assert before == after, "Every temporary hidden storage target must be gone"
            if sync.vault.view(rows[index]["id"])["status"] != "synced":
                observed = await browsers[index].snapshot()
                desired, _, _ = sync.vault.state(rows[index])
                await browsers[index].apply(desired, observed["snapshot"])
                raise AssertionError("Host synchronization failed")

        async def restart(index, already_stopped=False):
            if not already_stopped:
                await browsers[index].unbind()
                await contexts[index].close()
            contexts[index] = await api.chromium.launch_persistent_context(
                str(tmp_path / f"profile-{index}"),
                executable_path=BINARY,
                headless=True,
                chromium_sandbox=True,
            )
            browsers[index] = Browser()
            await browsers[index].bind(contexts[index], hashlib.sha256(uuid.uuid4().bytes).hexdigest())
            guests[f"guest-{index}"] = httpx.ASGITransport(app=guest_app(browsers[index], rows[index]["token"]))
            return browsers[index]

        a, b, c = browsers
        assert (await visit(a, "/login"))["token"] == "token-v1"
        await synced(0)
        await synced(1)
        # Server independently receives the HttpOnly cookie; destination JS sees LocalStorage.
        assert await visit(b, "/private") == {"cookie": "sid=v1", "token": "token-v1"}
        await synced(2)
        assert await visit(c, "/private") == {"cookie": "", "token": None}
        await visit(a, "/rotate")
        await synced(0)
        await synced(1)
        assert await visit(b, "/private") == {"cookie": "sid=v2", "token": "token-v2"}
        # Peer B is offline when logout happens; its persisted LocalStorage must
        # be cleared before it visits the site again after restart.
        await b.unbind()
        await contexts[1].close()
        await visit(a, "/logout")
        await synced(0)
        b = await restart(1, already_stopped=True)
        await synced(1)
        assert await visit(b, "/private") == {"cookie": "", "token": None}
        assert await visit(c, "/private") == {"cookie": "", "token": None}
        # A fresh login after the synchronized logout is still permitted.
        await visit(b, "/login")
        await synced(1)
        await synced(0)
        assert await visit(a, "/private") == {"cookie": "sid=v1", "token": "token-v1"}
        # A real browser restart must restore session cookies, never publish logout.
        a = await restart(0)
        await synced(0)
        assert await visit(a, "/private") == {"cookie": "sid=v1", "token": "token-v1"}
        # The browser accepted an apply, but the host did not receive its receipt.
        # Recovery reconciles the pending canonical state without publishing a false logout.
        original_request = sync.request

        async def lost_receipt(row, path, payload=None):
            result = await original_request(row, path, payload)
            if path == "apply":
                raise httpx.ReadTimeout("synthetic lost receipt")
            return result

        monkeypatch.setattr(sync, "request", lost_receipt)
        await sync.once(rows[1]["id"])
        assert sync.vault.view(rows[1]["id"])["status"] == "error"
        assert sync.vault.state(rows[1])[2]
        monkeypatch.setattr(sync, "request", original_request)
        await synced(1)
        assert await visit(b, "/private") == {"cookie": "sid=v1", "token": "token-v1"}
        empty = {"cookies": [], "origins": {}}
        async with client_type(transport=guests["guest-0"], base_url="http://guest-0") as client:
            assert (await client.get("/browser/snapshot")).status_code == 401
            assert (await client.post("/browser/apply", json={"state": {}, "expected": empty})).status_code == 401
        assert "/" not in Site.paths, "Synthetic storage documents must not contact the business server"
        proof = {
            "real_browsers": 3,
            "http_only_cookie": True,
            "local_storage": True,
            "storage_restore_no_business_requests": True,
            "logout_clear_and_redirect": True,
            "offline_peer_logout": True,
            "refresh": True,
            "logout": True,
            "new_login_after_logout": True,
            "cross_account_isolation": True,
            "real_browser_restart": True,
            "lost_receipt_reconciled": True,
        }
        output = os.getenv("CLAWITH_TEST_PROOF")
        if output:
            Path(output).write_text(json.dumps(proof, indent=2))
    finally:
        for browser in browsers:
            await browser.unbind()
        for context in contexts:
            await context.close()
        await api.stop()
        manager.db.close()
        server.shutdown()
        server.server_close()
