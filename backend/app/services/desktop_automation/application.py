"""Additive capability process: existing auth/DB/Tools, no Agent scheduler startup."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.desktop_automation import router

from .executor import PlaybackEngine
from .mcp import router as mcp_router
from .registry import AutomationRegistry
from .registry_mcp import router as registry_router
from .service import AutomationService
from .settings import Settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    service = AutomationService(Settings.load())
    engine = PlaybackEngine(service)
    app.state.desktop_automation = service
    app.state.desktop_playback = engine
    app.state.automation_registry = AutomationRegistry(service, engine)
    await engine.recover()
    maintenance = asyncio.create_task(engine.maintenance())
    yield
    maintenance.cancel()
    await asyncio.gather(maintenance, return_exceptions=True)
    await engine.close()


app = FastAPI(title="Clawith Desktop Automation", lifespan=lifespan)
app.include_router(router, prefix="/api")
app.include_router(registry_router)
app.include_router(mcp_router)


@app.exception_handler(ValueError)
async def invalid_input(request, exc):
    return JSONResponse({"detail": str(exc)[:1000]}, status_code=422)


@app.get("/health")
async def health():
    return {
        "ready": hasattr(app.state, "desktop_automation"),
        "capability": "desktop-recording",
        "driver": "cua",
        "version": "1",
    }
