"""One authenticated Cua provider. No Agent identity is fabricated for manual work."""

from __future__ import annotations

import base64
import fnmatch
import json
import uuid

import httpx

from .contracts import Step, Target, render
from .settings import Settings


class DriverFailure(RuntimeError):
    def __init__(self, message: str, *, uncertain: bool = False, condition_absent: bool = False):
        super().__init__(message[:1200])
        self.uncertain = uncertain
        self.condition_absent = condition_absent


def result_text(result: dict) -> str:
    return "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")[:60000]


class CuaDriver:
    def __init__(self, config: Settings):
        self.config = config
        self.runtime_contexts: dict[str, dict] = {}

    async def call(self, session: str, action: str, params: dict, request_id: str | None = None) -> dict:
        args = {"action": action, "params": params, "session_id": session}
        if request_id:
            args["request_id"] = request_id
        body = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": "tools/call",
            "params": {"name": "computer", "arguments": args},
        }
        if session in self.runtime_contexts:
            body["params"]["_meta"] = {"io.clawith/runtime": self.runtime_contexts[session]}
        try:
            async with (
                httpx.AsyncClient(timeout=httpx.Timeout(45, connect=5), trust_env=False) as client,
                client.stream(
                    "POST",
                    self.config.driver_url,
                    json=body,
                    headers={"Authorization": "Bearer " + self.config.driver_token},
                ) as response,
            ):
                response.raise_for_status()
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > 12 * 1024 * 1024:
                        raise DriverFailure("Desktop response exceeds its bound", uncertain=request_id is not None)
            result = json.loads(chunks).get("result", {})
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise DriverFailure(
                "Desktop connection interrupted. Inspect state before repeating input.",
                uncertain=request_id is not None,
            ) from exc
        if not isinstance(result, dict) or result.get("isError") or not isinstance(result.get("content"), list):
            detail = result_text(result) if isinstance(result, dict) else "Invalid desktop result"
            known_rejected = any(
                x in detail.lower()
                for x in [
                    "no action was dispatched",
                    "no screenshot of window",
                    "invalid arguments",
                    "in use by another",
                    "unknown argument",
                    "not exposed",
                ]
            )
            raise DriverFailure(
                detail or "Desktop action failed", uncertain=request_id is not None and not known_rejected
            )
        return result

    async def release(self, session: str) -> None:
        context = self.runtime_contexts.pop(session, None)
        native_session = "run_" + context["run_id"].replace("-", "") if context else session
        await self.call(native_session, "release", {})

    async def windows(self, session: str) -> list[dict]:
        result = await self.call(session, "list_windows", {})
        values = result.get("structuredContent", {}).get("windows", [])
        if not isinstance(values, list) or len(values) > 300:
            raise DriverFailure("Desktop window inventory is invalid or exceeds 300 windows")
        return [w for w in values if w.get("is_on_screen") and not w.get("minimized")]

    async def frame(self, session: str) -> dict:
        result = await self.call(session, "get_desktop_state", {})
        image = next((c for c in result.get("content", []) if c.get("type") == "image"), None)
        if image is None or len(image.get("data", "")) > 8 * 1024 * 1024:
            raise DriverFailure("Desktop screenshot is missing or exceeds 8 MiB")
        meta = result.get("structuredContent", {})
        return {
            "image": image["data"],
            "mime": image.get("mimeType", "image/png"),
            "width": meta.get("screenshot_width", 1280),
            "height": meta.get("screenshot_height", 800),
        }

    async def find(self, session: str, target: Target, inputs: dict[str, str]) -> dict:
        title = render(target.title, inputs)
        candidates = [
            w
            for w in await self.windows(session)
            if w.get("app_name", "").casefold() == target.app.casefold()
            and fnmatch.fnmatchcase(w.get("title", ""), title)
        ]
        if len(candidates) != 1:
            raise DriverFailure(
                f"Expected one window for {target.app} / {title}; found {len(candidates)}. Open or identify the target window before replay.",
                condition_absent=len(candidates) == 0,
            )
        return candidates[0]

    async def anchor(self, session: str, step: Step) -> Step:
        """Convert desktop pixels to fresh window-relative coordinates at recording time."""
        if step.target is not None:
            return step
        windows = sorted(await self.windows(session), key=lambda w: w.get("z_index", 0), reverse=True)
        if step.x is not None and step.y is not None:
            for w in windows:
                b = w.get("bounds", {})
                if (
                    w.get("app_name")
                    and w.get("title")
                    and b.get("x", 0) <= step.x < b.get("x", 0) + b.get("width", 0)
                    and b.get("y", 0) <= step.y < b.get("y", 0) + b.get("height", 0)
                ):
                    return step.model_copy(
                        update={
                            "target": Target(app=w["app_name"], title=w["title"]),
                            "x": step.x - b["x"],
                            "y": step.y - b["y"],
                        }
                    )
        windows = [w for w in windows if w.get("app_name") and w.get("title")]
        if windows and step.action in {"type_text", "press_key", "hotkey", "assert_text"}:
            w = windows[0]
            return step.model_copy(update={"target": Target(app=w["app_name"], title=w["title"])})
        return step

    async def execute(
        self, session: str, step: Step, inputs: dict[str, str], request_id: str, applications: dict[str, dict]
    ) -> dict:
        if step.action == "launch_app":
            app = applications.get(step.app)
            if not app:
                raise DriverFailure("Application is not configured for this desktop")
            return await self.call(
                session, "launch_app", {"path": app["path"], "additional_arguments": app.get("args", [])}, request_id
            )
        if step.action == "assert_text":
            if step.target is None:
                raise DriverFailure("A verification step must identify its window")
            w = await self.find(session, step.target, inputs)
            result = await self.call(
                session,
                "get_window_state",
                {"pid": w["pid"], "window_id": w["window_id"], "timeout_ms": 10000, "max_elements": 800},
            )
            expected = render(step.text, inputs)
            if expected not in result_text(result):
                raise DriverFailure(
                    "Expected text was not found in the target window: " + expected[:160], condition_absent=True
                )
            return result
        params: dict = {"scope": "desktop", "delivery_mode": "foreground"}
        if step.target and step.action in {"click", "double_click", "right_click"}:
            w = await self.find(session, step.target, inputs)
            params = {"scope": "desktop", "delivery_mode": "foreground"}
            bounds = w.get("bounds", {})
            if (
                step.x is None
                or step.y is None
                or step.x >= bounds.get("width", 0)
                or step.y >= bounds.get("height", 0)
            ):
                raise DriverFailure("Recorded position is outside the target window; inspect layout before replay")
            state = await self.call(
                session, "get_window_state", {"pid": w["pid"], "window_id": w["window_id"], "max_elements": 100}
            )
            meta = state.get("structuredContent", {})
            # Cua's window image omits the one-pixel frame on this Windows
            # provider. Convert from the bounds the recorder observed into the
            # provider's fresh image coordinates, and refuse unknown geometry.
            border_x = (bounds["width"] - meta.get("screenshot_width", bounds["width"])) / 2
            border_y = (bounds["height"] - meta.get("screenshot_height", bounds["height"])) / 2
            if not (0 <= border_x <= 2 and 0 <= border_y <= 2):
                raise DriverFailure("Window screenshot geometry changed; inspect before replay")
            params = {
                "pid": w["pid"],
                "window_id": w["window_id"],
                "delivery_mode": "foreground",
                "x": step.x - border_x,
                "y": step.y - border_y,
            }
        elif step.target and step.action in {"type_text", "press_key", "hotkey"}:
            # A benign title-bar click foregrounds the resolved window. Input uses
            # desktop mode because Windows UIA hotkey delivery can drop XAML keys.
            w = await self.find(session, step.target, inputs)
            b = w["bounds"]
            await self.frame(session)
            await self.call(
                session,
                "click",
                {
                    "scope": "desktop",
                    "x": b["x"] + min(100, b["width"] // 2),
                    "y": b["y"] + 12,
                    "delivery_mode": "foreground",
                },
                request_id + "_focus",
            )
        if step.action in {"click", "double_click", "right_click"}:
            if not step.target:
                await self.frame(session)
                params.update({"x": step.x, "y": step.y})
        elif step.action == "type_text":
            params["text"] = render(step.text, inputs)
        elif step.action in {"press_key", "hotkey"}:
            params.update({"key": step.key, "modifiers": step.modifiers})
        elif step.action == "scroll":
            params.update({"direction": step.direction, "amount": step.amount})
        action = "press_key" if step.action == "hotkey" else step.action
        return await self.call(session, action, params, request_id)

    @staticmethod
    def png(frame: dict) -> bytes:
        return base64.b64decode(frame["image"], validate=True)
