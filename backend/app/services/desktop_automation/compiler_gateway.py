"""Host-only compiler provider. Docker access is never mounted into Clawith."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import selectors
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .python_worker import WORKER_SOURCE

MAX_BYTES = 262144


def compile_isolated(payload: dict, image: str) -> dict:
    """One bounded pure-Python process, with no network, host mounts or credentials."""
    name = "clawith-python-plan-" + uuid.uuid4().hex
    args = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--user",
        "65534:65534",
        "--pids-limit",
        "16",
        "--memory",
        "128m",
        "--cpus",
        "0.5",
        "--ulimit",
        "cpu=3:3",
        "--tmpfs",
        "/tmp:size=8m,noexec,nosuid",
        "--entrypoint",
        "python",
        image,
        "-I",
        "-u",
        "-c",
        WORKER_SOURCE,
    ]
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = bytearray()
    selector = selectors.DefaultSelector()
    try:
        assert p.stdin is not None and p.stdout is not None
        p.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        p.stdin.close()
        selector.register(p.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not selector.select(0.2):
                if p.poll() is not None:
                    break
                continue
            chunk = os.read(p.stdout.fileno(), 65536)
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > MAX_BYTES:
                return {"ok": False, "diagnostic": {"code": "output_limit", "message": "脚本输出超过 256 KiB"}}
        else:
            return {
                "ok": False,
                "diagnostic": {"code": "time_limit", "message": "纯计算超过 10 秒；请缩小循环或拆分任务"},
            }
        try:
            result = json.loads(output)
            if not isinstance(result, dict) or "ok" not in result:
                raise ValueError("Invalid worker result")
            return result
        except ValueError:
            return {
                "ok": False,
                "diagnostic": {"code": "worker_failed", "message": "脚本进程退出或超出内存/CPU 限额，尚未执行桌面动作"},
            }
    finally:
        selector.close()
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10, check=False)
        if p.poll() is None:
            p.kill()
        p.wait(timeout=5)
        if p.stdout:
            p.stdout.close()
        if p.stderr:
            p.stderr.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--image", default="python:3.12-slim")
    parser.add_argument("--host", default="192.168.0.1")
    parser.add_argument("--port", type=int, default=18129)
    args = parser.parse_args()
    token = Path(args.token_file).read_text().strip()
    if len(token) < 32:
        raise RuntimeError("Compiler authentication is missing")
    image = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", args.image], text=True
    ).strip()
    fingerprint = hashlib.sha256((image + WORKER_SOURCE).encode()).hexdigest()
    slots = threading.BoundedSemaphore(2)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def reply(self, result, status=200):
            raw = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self.reply({"ready": True, "compiler_fingerprint": fingerprint, "network": "none", "host_mounts": False})

        def do_POST(self):
            if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                return self.reply({"error": "Unauthorized"}, 401)
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self.reply({"error": "Invalid content length"}, 400)
            if not 0 < size <= MAX_BYTES:
                return self.reply({"error": "Request exceeds 256 KiB"}, 413)
            try:
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict) or set(payload) != {"source", "inputs", "secret_parameters"}:
                    raise ValueError("Invalid compiler payload")
                if not isinstance(payload["source"], str) or len(payload["source"].encode()) > 131072:
                    raise ValueError("Invalid Python source")
                if not isinstance(payload["inputs"], dict) or not isinstance(payload["secret_parameters"], list):
                    raise TypeError("Invalid Python parameters")
            except (ValueError, TypeError):
                return self.reply({"error": "Invalid compiler request"}, 422)
            if not slots.acquire(blocking=False):
                return self.reply(
                    {"ok": False, "diagnostic": {"code": "compiler_busy", "message": "编译环境正在忙，请稍后重试"}}
                )
            try:
                result = compile_isolated(payload, image)
                result["compiler_fingerprint"] = fingerprint
                self.reply(result)
            finally:
                slots.release()

    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
