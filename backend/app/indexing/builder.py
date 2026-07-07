from __future__ import annotations

import logging
import pickle
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import Settings, get_settings
from app.indexing.loader import fetch_all_products, normalize_products

logger = logging.getLogger(__name__)


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

    logger.info("Loading embedding model: %s", cfg.embedding_model)
    model = SentenceTransformer(cfg.embedding_model)

    logger.info("Encoding %d product texts", len(texts))
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    if not isinstance(embeddings, np.ndarray) or embeddings.ndim != 2:
        raise RuntimeError("Embedding model returned unexpected output shape")

    logger.info("Building FAISS cosine similarity index")
    index = build_faiss_index(embeddings)

    faiss.write_index(index, str(index_path))
    with products_path.open("wb") as file:
        pickle.dump(products, file)

    logger.info("Saved index to %s", index_path)
    logger.info("Saved products to %s", products_path)
    return len(products)
