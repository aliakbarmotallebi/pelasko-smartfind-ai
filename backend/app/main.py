from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette import status

from app.api import api_router
from app.config import get_settings
from app.services.gapgpt import GapGPTClient
from app.services.scheduler import start_index_scheduler, stop_index_scheduler
from app.services.search_engine import SearchEngine

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting Pelasko SmartFind AI service")
    scheduler = None

    try:
        app.state.search_engine = SearchEngine(settings=settings, auto_build=True)
        app.state.gapgpt_client = GapGPTClient(settings=settings)
        scheduler = start_index_scheduler(app.state.search_engine, settings)

        if not settings.gapgpt_enabled:
            logger.warning("GAPGPT_API_KEY is not set; fallback responses will be used")
    except Exception as exc:
        logger.exception("Failed to initialize application: %s", exc)
        raise

    yield

    stop_index_scheduler(scheduler)
    logger.info("Shutting down Pelasko SmartFind AI service")
    app.state.search_engine = None
    app.state.gapgpt_client = None


def create_app() -> FastAPI:
    application = FastAPI(
        title="Pelasko SmartFind AI",
        description="Persian AI shopping assistant with FAISS semantic search and GapGPT",
        version="2.2.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router)

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(_: FastAPI, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    return application


app = create_app()
