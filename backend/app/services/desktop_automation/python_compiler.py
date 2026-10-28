"""Authenticated pure-planning compiler; it never receives secret input values."""

from __future__ import annotations

import hashlib
import json

import httpx
from pydantic import ValidationError

from .code_contracts import CodePlan, PythonScript
from .settings import Settings


class CompilationError(ValueError):
    def __init__(self, diagnostic: dict):
        super().__init__(diagnostic.get("message", "Python compilation failed"))
        self.diagnostic = diagnostic


class PythonCompiler:
    def __init__(self, config: Settings):
        self.config = config

    async def compile(self, script: PythonScript, inputs: dict[str, str]) -> tuple[CodePlan, dict]:
        if not self.config.compiler_url or not self.config.compiler_token:
            raise CompilationError(
                {"code": "compiler_unavailable", "message": "Python 执行环境未配置，请联系平台管理员"}
            )
        payload = {
            "source": script.source,
            "inputs": {k: v for k, v in inputs.items() if k not in script.secret_parameters},
            "secret_parameters": script.secret_parameters,
        }
        try:
            async with (
                httpx.AsyncClient(timeout=httpx.Timeout(20, connect=3), trust_env=False) as client,
                client.stream(
                    "POST",
                    self.config.compiler_url,
                    json=payload,
                    headers={"Authorization": "Bearer " + self.config.compiler_token},
                ) as response,
            ):
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 262144:
                        raise CompilationError({"code": "output_limit", "message": "编译结果过大，请缩小单次任务"})
            result = json.loads(raw)
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise CompilationError(
                {"code": "compiler_unavailable", "message": "Python 编译连接失败；尚未执行任何桌面动作，可重新测试"}
            ) from exc
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
            raise CompilationError({"code": "compiler_protocol", "message": "Python 编译环境返回无效结果"})
        if not result["ok"]:
            d = result.get("diagnostic", {})
            raise CompilationError(
                {
                    "code": str(d.get("code", "compile_failed"))[:80],
                    "message": str(d.get("message", "Python 编译失败"))[:1200],
                    "line": d.get("line") if isinstance(d.get("line"), int) else None,
                }
            )
        try:
            plan = CodePlan.model_validate(result["plan"])
            plan.validate_source(script)
            fingerprint = result["compiler_fingerprint"]
            if not isinstance(fingerprint, str) or len(fingerprint) != 64:
                raise ValueError("Invalid compiler identity")
        except (KeyError, ValidationError, ValueError) as exc:
            raise CompilationError({"code": "plan_invalid", "message": str(exc)[:1200]}) from exc
        return plan, {
            "compiler_fingerprint": fingerprint,
            "compiler_stdout": str(result.get("stdout", ""))[:8192],
            "execution_plan_digest": hashlib.sha256(json.dumps(plan.model_dump(), sort_keys=True).encode()).hexdigest(),
        }
