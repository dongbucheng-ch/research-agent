"""FastAPI application entrypoint (also serves the built frontend)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.deps import require_token
from app.api.routes import articles, digests, items, jobs, schedules, sources, stats
from app.api.routes import settings as settings_routes
from app.core.config import get_settings
from app.core.db import dispose_engine, ensure_schema
from app.core.logging import setup_logging
from app.services.jobs import JobExecutor
from app.services.schedules import CollectionScheduler

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_create_tables:
            await ensure_schema()
        executor = JobExecutor()
        try:
            recovered = await executor.recover_stale()
            if recovered:
                logger.warning("marked %s interrupted job(s) as failed", recovered)
        except Exception:  # noqa: BLE001 - startup must not depend on recovery
            logger.exception("stale job recovery failed")
        app.state.executor = executor
        scheduler = CollectionScheduler(executor)
        scheduler.start()
        app.state.scheduler = scheduler
        yield
        await scheduler.stop()
        await dispose_engine()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
    api.include_router(sources.router)
    api.include_router(items.router)
    api.include_router(digests.router)
    api.include_router(articles.router)
    api.include_router(jobs.router)
    api.include_router(schedules.router)
    api.include_router(settings_routes.router)
    api.include_router(stats.router)
    app.include_router(api)

    if FRONTEND_DIST.exists():
        assets = FRONTEND_DIST / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="not found")
            index = FRONTEND_DIST / "index.html"
            if not index.exists():
                raise HTTPException(status_code=404, detail="frontend not built")
            return FileResponse(index)

    return app


app = create_app()
