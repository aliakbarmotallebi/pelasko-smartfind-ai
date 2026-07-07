from __future__ import annotations

import logging
import pickle
import threading
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import Settings, get_settings
from app.indexing.builder import build_index
from app.indexing.loader import to_product_data
from app.models import ProductData

logger = logging.getLogger(__name__)


class SearchEngine:
    def __init__(self, settings: Settings | None = None, auto_build: bool = True) -> None:
        self._settings = settings or get_settings()
        self._auto_build = auto_build
        self._lock = threading.RLock()

        self._index: faiss.IndexFlatIP | None = None
        self._products: list[dict[str, Any]] | None = None
        self._model: SentenceTransformer | None = None

        self._load_resources()

    @property
    def index_path(self) -> Path:
        return Path(self._settings.index_path)

    @property
    def products_path(self) -> Path:
        return Path(self._settings.products_path)

    def _ensure_index_files(self) -> None:
        if self.index_path.exists() and self.products_path.exists():
            return
        if not self._auto_build:
            raise FileNotFoundError(
                f"Index files not found in {self._settings.data_dir}. "
                "Run build_index script or POST /rebuild first."
            )
        logger.warning("Index files missing; building index automatically")
        build_index(self._settings)

    def _load_model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading embedding model: %s", self._settings.embedding_model)
            self._model = SentenceTransformer(self._settings.embedding_model)
        return self._model

    def _load_index_and_products(self) -> None:
        self._ensure_index_files()

        logger.info("Loading FAISS index from %s", self.index_path)
        index = faiss.read_index(str(self.index_path))
        if not isinstance(index, faiss.IndexFlatIP):
            raise RuntimeError("Expected FAISS IndexFlatIP for cosine similarity search")

        logger.info("Loading products from %s", self.products_path)
        with self.products_path.open("rb") as file:
            products = pickle.load(file)

        if not isinstance(products, list):
            raise RuntimeError("Products file has invalid format")

        self._index = index
        self._products = products
        logger.info("Search engine ready with %d indexed products", len(products))

    def _load_resources(self) -> None:
        with self._lock:
            self._load_index_and_products()
            self._load_model()

    def reload(self) -> int:
        with self._lock:
            logger.info("Rebuilding search index")
            total = build_index(self._settings)
            self._index = None
            self._products = None
            self._load_index_and_products()
            return total

    def search(self, query: str, top_k: int | None = None) -> list[ProductData]:
        normalized_query = query.strip()
        if not normalized_query:
            return []

        limit = top_k or self._settings.search_top_k

        with self._lock:
            if self._index is None or self._products is None:
                raise RuntimeError("Search engine is not initialized")

            model = self._load_model()
            query_embedding = model.encode(
                [normalized_query],
                convert_to_numpy=True,
                normalize_embeddings=True,
            )

            if not isinstance(query_embedding, np.ndarray):
                raise RuntimeError("Failed to encode query")

            scores, indices = self._index.search(
                query_embedding.astype(np.float32),
                min(limit, len(self._products)),
            )

            results: list[ProductData] = []
            for score, idx in zip(scores[0], indices[0], strict=True):
                if idx < 0:
                    continue
                item = self._products[idx]
                results.append(
                    to_product_data(
                        item,
                        self._settings.product_base_url,
                        score=float(score),
                    )
                )
            return results
