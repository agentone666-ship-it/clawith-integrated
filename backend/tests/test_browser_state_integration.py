"""Real browser processes + shipped guest routes + host sync, without user profiles."""

import ast
import asyncio
import json
import os
import subprocess
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
    site = f"http://127.0.0.1:{server.server_port}"
    processes, browsers = [], []
    manager = Manager(tmp_path / "private.sqlite", SimpleNamespace(root=tmp_path))
    sync = BrowserSync(manager, tmp_path / "vault.key")
    manager.browser_sync = sync
    rows, guests = [], {}
    client_type = httpx.AsyncClient
    try:
        tenant, owner = str(uuid.uuid4()), str(uuid.uuid4())
        for i in range(3):
            profile = tmp_path / f"profile-{i}"
            process = await asyncio.create_subprocess_exec(
                BINARY,
                "--headless=new",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-port=0",
                "--user-data-dir=" + str(profile),
                "about:blank",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(process)
            for _ in range(100):
                if (profile / "DevToolsActivePort").exists():
                    break
                await asyncio.sleep(0.1)
            port = (profile / "DevToolsActivePort").read_text().splitlines()[0]
            browser = Browser(f"http://127.0.0.1:{port}/json/version")
            browsers.append(browser)
            await browser.start()
            await until(browser.snapshot, lambda v: v.get("connected"))
            ident = manager.create(
                {"tenant_id": tenant, "owner_id": owner if i < 2 else str(uuid.uuid4()), "agent_id": str(uuid.uuid4())}
            )
            manager.db.execute("UPDATE desktops SET state='ready',ip=? WHERE id=?", (f"guest-{i}", ident))
            manager.db.commit()
            row = manager.row(ident)
            rows.append(row)
            guests[f"guest-{i}"] = httpx.ASGITransport(app=guest_app(browser, row["token"]))

        async def dispatch(request):
            return await guests[request.url.host].handle_async_request(request)

        monkeypatch.setattr(
            "app.services.desktop_automation.sandbox_host.browser_sync.httpx.AsyncClient",
            lambda **kw: client_type(transport=httpx.MockTransport(dispatch), **kw),
        )

        async def visit(browser, path):
            created = await browser.call("Target.createTarget", {"url": site + path})
            for _ in range(100):
                for sid, state in list(browser.sessions.items()):
                    if state.get("ready") and state.get("target") == created["targetId"]:
                        frame = await browser.call("Page.getFrameTree", sid=sid)
                        if frame["frameTree"]["frame"]["url"] == site + ("/signed-out" if path == "/logout" else path):
                            result = await browser.call(
                                "Runtime.evaluate",
                                {
                                    "expression": "JSON.stringify({cookie:document.getElementById('server')?.textContent,token:localStorage.getItem('access_token')})",
                                    "returnByValue": True,
                                },
                                sid,
                            )
                            value = json.loads(result["result"]["value"])
                            if value.get("cookie") is not None:
                                return value
                await asyncio.sleep(0.1)
            raise AssertionError("Page was not loaded: " + created["targetId"])

        async def synced(index):
            await sync.once(rows[index]["id"])
            if sync.vault.view(rows[index]["id"])["status"] != "synced":
                observed = await browsers[index].snapshot()
                desired, _, _ = sync.vault.state(rows[index])
                await browsers[index].apply(desired, observed["snapshot"])
                raise AssertionError("Host synchronization failed")

        async def restart(index, already_stopped=False):
            if not already_stopped:
                await browsers[index].stop()
                processes[index].terminate()
                await asyncio.wait_for(processes[index].wait(), 10)
            profile = tmp_path / f"profile-{index}"
            (profile / "DevToolsActivePort").unlink(missing_ok=True)
            processes[index] = await asyncio.create_subprocess_exec(
                BINARY,
                "--headless=new",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-port=0",
                "--user-data-dir=" + str(profile),
                "about:blank",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(100):
                if (profile / "DevToolsActivePort").exists():
                    break
                await asyncio.sleep(0.1)
            port = (profile / "DevToolsActivePort").read_text().splitlines()[0]
            browsers[index] = Browser(f"http://127.0.0.1:{port}/json/version")
            await browsers[index].start()
            await until(browsers[index].snapshot, lambda v: v.get("connected"))
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
        await b.stop()
        processes[1].terminate()
        await asyncio.wait_for(processes[1].wait(), 10)
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
            await browser.stop()
        for process in processes:
            process.terminate()
            await asyncio.wait_for(process.wait(), 10)
        manager.db.close()
        server.shutdown()
        server.server_close()
