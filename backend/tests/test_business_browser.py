"""Owned browser lifecycle, private storage deadlines, and task-safe launch."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("playwright.async_api")

from app.services.desktop_automation.sandbox_host.browser_guest import Document
from app.services.desktop_automation.sandbox_host.business_browser import BusinessBrowser


@pytest.mark.parametrize(
    "value", [False, 0, "", "--remote-debugging-port=1", ["--load-extension=x"], ["https://example.test"] * 9]
)
def test_browser_launch_accepts_only_bounded_urls(value):
    with pytest.raises(RuntimeError, match="HTTP"):
        BusinessBrowser.validate_urls(value)


def test_browser_launch_accepts_empty_or_eight_urls():
    assert BusinessBrowser.validate_urls(None) == []
    assert len(BusinessBrowser.validate_urls(["https://example.test"] * 8)) == 8


async def test_storage_deadline_covers_transport_backpressure(monkeypatch):
    from app.services.desktop_automation.sandbox_host import browser_guest as module

    monkeypatch.setattr(module, "REQUEST_TIMEOUT", 0.02)
    never = asyncio.Event()

    async def send(method, params):
        await never.wait()

    document = Document(SimpleNamespace(send=send))
    document.sid = "test-session"
    with pytest.raises(RuntimeError, match="did not complete"):
        await document.call("Page.navigate", {"url": "https://example.test"})
    assert not document.pending


@pytest.mark.parametrize("path", ["snapshot", "apply"])
async def test_private_sync_deadline_includes_lock_acquisition(path):
    import httpx
    from test_browser_state_integration import guest_app

    lock = asyncio.Lock()
    await lock.acquire()
    app = guest_app(SimpleNamespace(lock=lock), "test-only-secret")
    for route in app.routes:
        if getattr(route, "path", "").startswith("/browser/"):
            route.endpoint.__globals__["asyncio"] = SimpleNamespace(timeout=lambda _: asyncio.timeout(0.02))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://guest") as client:
        async with asyncio.timeout(0.5):
            response = await client.request(
                "GET" if path == "snapshot" else "POST",
                "/browser/" + path,
                headers={"Authorization": "Bearer test-only-secret"},
                json={"state": {}, "expected": {}} if path == "apply" else None,
            )
    assert response.status_code == 409 and lock.locked()
    lock.release()
