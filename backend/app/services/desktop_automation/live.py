"""Execution-owned latest frame; HTTP observers never touch the desktop lease."""

import asyncio
import base64
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from .driver import DriverFailure
from .service import fail

log = logging.getLogger(__name__)


def store(service, ident, frame):
    try:
        data = service.driver.png(frame)
        if len(data) > 8 * 1024 * 1024:
            return
        folder = service.config.evidence_dir / str(ident)
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / "live.tmp"
        temporary.write_bytes(data)
        os.replace(temporary, folder / "live.png")
    except (OSError, ValueError):
        log.warning("Could not update desktop live frame for %s", ident, exc_info=True)


async def pump(service, ident, session):
    while True:
        try:
            async with service.lock:
                value = await service.driver.frame(session)
                store(service, ident, value)
        except (DriverFailure, OSError, ValueError):
            log.warning("Desktop live capture delayed for %s", ident, exc_info=True)
        await asyncio.sleep(0.8)


async def latest_frame(engine, db, user, ident):
    await engine.get(db, user, ident)
    path: Path = engine.service.config.evidence_dir / str(ident) / "live.png"
    try:
        with path.open("rb") as handle:
            stat = os.fstat(handle.fileno())
            data = handle.read(8 * 1024 * 1024 + 1)
    except FileNotFoundError:
        fail(404, "Live frame is not available yet")
    if len(data) > 8 * 1024 * 1024:
        fail(413, "Live frame exceeds size limit")
    return {
        "image": base64.b64encode(data).decode(),
        "mime": "image/png",
        "sequence": str(stat.st_mtime_ns),
        "captured_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }
