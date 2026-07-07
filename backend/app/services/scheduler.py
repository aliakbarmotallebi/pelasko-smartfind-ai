from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Settings

if TYPE_CHECKING:
    from app.services.search_engine import SearchEngine

logger = logging.getLogger(__name__)


async def _run_scheduled_rebuild(search_engine: SearchEngine) -> None:
    logger.info("Starting scheduled index rebuild")
    try:
        total = await asyncio.to_thread(search_engine.reload)
        logger.info("Scheduled index rebuild completed (%d products)", total)
    except Exception as exc:
        logger.exception("Scheduled index rebuild failed: %s", exc)


def start_index_scheduler(
    search_engine: SearchEngine,
    settings: Settings,
) -> AsyncIOScheduler | None:
    if not settings.index_rebuild_enabled:
        logger.info("Scheduled index rebuild is disabled")
        return None

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_scheduled_rebuild,
        trigger=IntervalTrigger(hours=settings.index_rebuild_interval_hours),
        args=[search_engine],
        id="rebuild_product_index",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "Scheduled index rebuild every %d hour(s)",
        settings.index_rebuild_interval_hours,
    )
    return scheduler


def stop_index_scheduler(scheduler: AsyncIOScheduler | None) -> None:
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        logger.info("Index rebuild scheduler stopped")
