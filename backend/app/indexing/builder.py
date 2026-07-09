from __future__ import annotations

import json
import logging
import pickle
from datetime import UTC, datetime
from pathlib import Path

import faiss
import numpy as np

from app.config import Settings, get_settings
from app.services.embeddings import create_embedding_backend
from app.indexing.loader import fetch_all_products, normalize_products

logger = logging.getLogger(__name__)

INDEX_META_FILENAME = "index_meta.json"


def index_meta_path(data_dir: str) -> Path:
    return Path(data_dir) / INDEX_META_FILENAME


def save_index_meta(cfg: Settings, total_products: int) -> None:
    meta = {
        "embedding_model": cfg.embedding_model,
        "total_products": total_products,
        "built_at": datetime.now(UTC).isoformat(),
    }
    path = index_meta_path(cfg.data_dir)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved index metadata to %s", path)


def read_index_meta(data_dir: str) -> dict | None:
    path = index_meta_path(data_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read index metadata: %s", exc)
        return None


def build_faiss_index(embeddings: np.ndarray) -> faiss.IndexFlatIP:
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings.astype(np.float32))
    return index


def build_index(settings: Settings | None = None) -> int:
    cfg = settings or get_settings()
    output_dir = Path(cfg.data_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    index_path = Path(cfg.index_path)
    products_path = Path(cfg.products_path)

    raw_products = fetch_all_products(cfg)
    if not raw_products:
        raise RuntimeError("No products returned from API")

    products = normalize_products(raw_products, cfg.product_base_url)
    texts = [item["search_text"] for item in products]

    model = create_embedding_backend(cfg)

    logger.info("Encoding %d product texts with %s", len(texts), model.model_name)
    embeddings = model.encode_passages(
        texts,
        batch_size=32,
        show_progress_bar=True,
    )

    logger.info("Building FAISS cosine similarity index")
    index = build_faiss_index(embeddings)

    faiss.write_index(index, str(index_path))
    with products_path.open("wb") as file:
        pickle.dump(products, file)

    save_index_meta(cfg, len(products))

    logger.info("Saved index to %s", index_path)
    logger.info("Saved products to %s", products_path)
    return len(products)
