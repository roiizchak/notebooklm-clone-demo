"""FastAPI app entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.middleware.request_id import RequestIDMiddleware, install_logging_filter
from app.routers import (
    audio,
    chat,
    config as config_router,
    notebooks,
    notes,
    profile,
    research,
    sources,
    studies,
)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="API-first research intelligence platform (Phase 2)",
        debug=settings.debug,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    install_logging_filter()
    app.add_middleware(RequestIDMiddleware)

    app.include_router(notebooks.router, prefix="/api/v1", tags=["Notebooks"])
    app.include_router(sources.router, prefix="/api/v1", tags=["Sources"])
    app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
    app.include_router(profile.router, prefix="/api/v1", tags=["Profile"])
    app.include_router(studies.router, prefix="/api/v1", tags=["Studies"])
    app.include_router(notes.router, prefix="/api/v1", tags=["Notes"])
    app.include_router(audio.router, prefix="/api/v1", tags=["Audio"])
    app.include_router(research.router, prefix="/api/v1", tags=["Research"])
    app.include_router(config_router.router)

    @app.get("/")
    async def root() -> dict:
        return {"message": settings.app_name, "docs": "/docs"}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "healthy"}

    return app


app = create_app()
