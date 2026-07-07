from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.models import RebuildResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["index"])


@router.post("/rebuild", response_model=RebuildResponse)
async def rebuild(request: Request) -> RebuildResponse:
    search_engine = getattr(request.app.state, "search_engine", None)
    if search_engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search engine is not ready",
        )

    try:
        total = search_engine.reload()
        return RebuildResponse(
            status="success",
            total_products=total,
            message=f"Index rebuilt with {total} products",
        )
    except Exception as exc:
        logger.exception("Index rebuild failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Index rebuild failed",
        ) from exc
