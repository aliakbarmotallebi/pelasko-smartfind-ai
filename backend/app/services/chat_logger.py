from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.models import ProductData

logger = logging.getLogger(__name__)


def _product_to_dict(product: ProductData) -> dict[str, Any]:
    return product.model_dump()


def _embedding_summary(vector: list[float], preview_size: int = 10) -> dict[str, Any]:
    if not vector:
        return {"dimension": 0, "norm": 0.0, "preview": [], "vector": []}

    norm = sum(value * value for value in vector) ** 0.5
    preview = vector[:preview_size]
    return {
        "dimension": len(vector),
        "norm": round(norm, 6),
        "preview": [round(value, 6) for value in preview],
        "vector": [round(value, 6) for value in vector],
    }


@dataclass
class ChatTrace:
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    client_host: str = "unknown"
    user_message: str = ""

    llm_query_extraction: dict[str, Any] = field(default_factory=dict)
    embedding: dict[str, Any] = field(default_factory=dict)
    search: dict[str, Any] = field(default_factory=dict)
    llm_rerank: dict[str, Any] = field(default_factory=dict)
    llm_sales: dict[str, Any] = field(default_factory=dict)
    sent_to_user: dict[str, Any] = field(default_factory=dict)
    finished_at: str | None = None
    error: str | None = None

    def finish(self) -> None:
        self.finished_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChatLogger:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._log_dir = Path(self._settings.chat_log_dir).expanduser()
        if not self._log_dir.is_absolute():
            self._log_dir = Path.cwd() / self._log_dir

    def new_trace(self, *, client_host: str, user_message: str) -> ChatTrace:
        return ChatTrace(client_host=client_host, user_message=user_message)

    def save(self, trace: ChatTrace) -> Path | None:
        if not self._settings.chat_log_enabled:
            return None

        trace.finish()
        self._log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"chat_{timestamp}_{trace.trace_id}.json"
        path = self._log_dir / filename

        payload = trace.to_dict()
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Chat trace saved to %s", path)
        return path


def build_embedding_log(
    *,
    query: str,
    model_name: str,
    vector: list[float],
) -> dict[str, Any]:
    return {
        "query": query,
        "model": model_name,
        **_embedding_summary(vector),
    }


def build_search_log(
    *,
    query: str,
    min_score: float,
    top_k: int,
    hits: list[dict[str, Any]],
    results: list[ProductData],
) -> dict[str, Any]:
    return {
        "query": query,
        "min_score": min_score,
        "top_k": top_k,
        "hits": hits,
        "results": [_product_to_dict(product) for product in results],
        "result_count": len(results),
    }


_chat_logger: ChatLogger | None = None


def get_chat_logger() -> ChatLogger:
    global _chat_logger
    if _chat_logger is None:
        _chat_logger = ChatLogger()
    return _chat_logger
