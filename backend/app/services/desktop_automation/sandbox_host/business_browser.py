"""Own the dedicated visible business browser via Playwright's private pipe.

Desktop input remains Cua Driver's responsibility. No existing/default user
profile or arbitrary debugging endpoint is attached to this browser owner.
"""

import asyncio
import hashlib
import uuid

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PROFILE = r"C:\Users\Clawith\AppData\Local\CuaDriver\BrowserProfiles\clawith-business-v1"


class BusinessBrowser:
    def __init__(self, browser):
        self.browser = browser
        self.api = None
        self.manager = None
        self.identity = ""
        self.context = None
        self.stage = "waiting"
        self.lock = asyncio.Lock()

    async def start(self):
        self.manager = async_playwright()
        try:
            async with asyncio.timeout(30):
                self.api = await self.manager.start()
        except BaseException:
            async with asyncio.timeout(10):
                await self.manager.__aexit__(None, None, None)
            self.manager = None
            raise

    async def stop(self):
        async with self.lock, self.browser.lock:
            await self.browser.unbind()
            if self.context and self.context.browser and self.context.browser.is_connected():
                await self.context.close()
            self.context = None
            if self.api:
                await self.api.stop()
                self.api = None
                self.manager = None
            self.stage = "closed"

    @staticmethod
    def validate_urls(urls):
        if urls is None:
            return []
        if (
            not isinstance(urls, list)
            or len(urls) > 8
            or any(
                not isinstance(url, str)
                or len(url) > 2048
                or not (url.startswith(("https://", "http://")) or url == "about:blank")
                for url in urls
            )
        ):
            raise RuntimeError("Business browser accepts at most eight HTTP(S) URLs")
        return urls

    async def prepare(self, urls=None):
        self.validate_urls(urls)
        try:
            async with asyncio.timeout(110), self.lock:
                if not self.api:
                    await self.start()
                if not self.browser.connected:
                    self.stage = "launching"
                    assert self.api is not None
                    self.context = await self.api.chromium.launch_persistent_context(
                        PROFILE,
                        executable_path=EDGE,
                        headless=False,
                        no_viewport=True,
                        chromium_sandbox=True,
                        args=["--no-first-run", "--no-default-browser-check", "--start-maximized"],
                        timeout=90000,
                    )
                    self.identity = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
                    await self.browser.bind(self.context, self.identity)
                self.stage = "ready"
                return {
                    "content": [{"type": "text", "text": "Business browser opened."}],
                    "structuredContent": {"business_browser_prepared": True},
                }
        except (PlaywrightError, TimeoutError) as exc:
            self.stage = "error"
            raise RuntimeError(
                "Business browser did not become ready; inspect the cloud desktop before retrying"
            ) from exc

    async def navigate(self, urls):
        urls = self.validate_urls(urls)
        if not self.browser.connected or not self.context:
            raise RuntimeError("Business browser closed before navigation; inspect desktop")
        try:
            for url in urls:
                page = await self.context.new_page()
                await page.goto(url, wait_until="commit", timeout=10000)
                await page.bring_to_front()
        except PlaywrightError as exc:
            raise RuntimeError("Browser navigation did not complete; inspect desktop before repeating input") from exc
