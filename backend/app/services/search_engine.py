from __future__ import annotations

import logging
import pickle
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from app.config import Settings, get_settings
from app.services.embeddings import EmbeddingBackend, create_embedding_backend
from app.services.lexical_search import (
    build_token_weights,
    has_strong_title_match,
    title_match_score,
)
from app.indexing.builder import build_index, read_index_meta
from app.indexing.loader import to_product_data
from app.models import ProductData

logger = logging.getLogger(__name__)


@dataclass
class SearchHitDetail:
    product: ProductData
    score: float
    vector_score: float
    lexical_score: float
    passed_min_score: bool
    in_stock: bool


@dataclass
class SearchDetails:
    query: str
    embedding_model: str
    embedding_vector: list[float]
    min_score: float
    top_k: int
    hits: list[SearchHitDetail]
    results: list[ProductData]


class SearchEngine:
    def __init__(self, settings: Settings | None = None, auto_build: bool = True) -> None:
        self._settings = settings or get_settings()
        self._auto_build = auto_build
        self._lock = threading.RLock()

        self._index: faiss.IndexFlatIP | None = None
        self._products: list[dict[str, Any]] | None = None
        self._model: EmbeddingBackend | None = None

        self._load_resources()

    @property
    def index_path(self) -> Path:
        return Path(self._settings.index_path)

    @property
    def products_path(self) -> Path:
        return Path(self._settings.products_path)

    def _ensure_index_files(self) -> None:
        if self.index_path.exists() and self.products_path.exists():
            self._ensure_index_matches_model()
            return
        if not self._auto_build:
            raise FileNotFoundError(
                f"Index files not found in {self._settings.data_dir}. "
                "Run build_index script or POST /rebuild first."
            )
        logger.warning("Index files missing; building index automatically")
        build_index(self._settings)

    def _ensure_index_matches_model(self) -> None:
        meta = read_index_meta(self._settings.data_dir)
        if meta is None:
            logger.warning("Index metadata missing; rebuilding index")
            build_index(self._settings)
            return

        indexed_model = str(meta.get("embedding_model", "")).strip()
        current_model = self._settings.embedding_model.strip()
        if indexed_model and indexed_model != current_model:
            logger.warning(
                "Index was built with '%s' but current model is '%s'; rebuilding index",
                indexed_model,
                current_model,
            )
            build_index(self._settings)

    def _load_model(self) -> EmbeddingBackend:
        if self._model is None:
            self._model = create_embedding_backend(self._settings)
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
        return self.search_with_details(query, top_k=top_k).results

    def search_with_details(self, query: str, top_k: int | None = None) -> SearchDetails:
        normalized_query = query.strip()
        if not normalized_query:
            return SearchDetails(
                query="",
                embedding_model=self._settings.embedding_model,
                embedding_vector=[],
                min_score=self._settings.search_min_score,
                top_k=top_k or self._settings.search_top_k,
                hits=[],
                results=[],
            )

        limit = top_k or self._settings.search_top_k
        pool_size = min(
            self._settings.search_candidate_pool,
            len(self._products),
        )

        with self._lock:
            if self._index is None or self._products is None:
                raise RuntimeError("Search engine is not initialized")

            model = self._load_model()
            query_embedding = model.encode_queries([normalized_query])

            if not isinstance(query_embedding, np.ndarray):
                raise RuntimeError("Failed to encode query")

            embedding_vector = query_embedding[0].astype(float).tolist()

            scores, indices = self._index.search(
                query_embedding.astype(np.float32),
                pool_size,
            )

            product_names = [str(item.get("name", "")) for item in self._products]
            token_weights = build_token_weights(normalized_query, product_names)
            vector_weight = self._settings.search_vector_weight
            lexical_weight = self._settings.search_lexical_weight
            weight_total = vector_weight + lexical_weight
            if weight_total <= 0:
                vector_weight, lexical_weight, weight_total = 0.55, 0.45, 1.0
            vector_weight /= weight_total
            lexical_weight /= weight_total

            min_score = self._settings.search_min_score
            ranked_hits: list[SearchHitDetail] = []
            best_score = 0.0

            for score, idx in zip(scores[0], indices[0], strict=True):
                if idx < 0:
                    continue

                vector_score = float(score)
                item = self._products[idx]
                product_name = str(item.get("name", ""))
                lexical_score = title_match_score(
                    normalized_query,
                    product_name,
                    token_weights,
                )
                hybrid_score = (vector_weight * vector_score) + (lexical_weight * lexical_score)
                if hybrid_score > best_score:
                    best_score = hybrid_score

                in_stock = bool(item.get("in_stock", True))
                passed_min_score = hybrid_score >= min_score
                product = to_product_data(
                    item,
                    self._settings.product_base_url,
                    score=hybrid_score,
                )
                ranked_hits.append(
                    SearchHitDetail(
                        product=product,
                        score=hybrid_score,
                        vector_score=vector_score,
                        lexical_score=lexical_score,
                        passed_min_score=passed_min_score,
                        in_stock=in_stock,
                    )
                )

            ranked_hits.sort(key=lambda hit: hit.score, reverse=True)
            hits = ranked_hits[:limit]
            results = [
                hit.product for hit in hits if hit.passed_min_score and hit.in_stock
            ]

            if not results:
                logger.info(
                    "No products matched query '%s' (best_score=%.4f, min_score=%.2f)",
                    normalized_query,
                    best_score,
                    min_score,
                )

            return SearchDetails(
                query=normalized_query,
                embedding_model=model.model_name,
                embedding_vector=embedding_vector,
                min_score=min_score,
                top_k=limit,
                hits=hits,
                results=results,
            )


def should_skip_rerank(
    query: str,
    hits: list[SearchHitDetail],
    settings: Settings | None = None,
) -> bool:
    if len(hits) <= 1:
        return True

    cfg = settings or get_settings()
    top = hits[0]
    second = hits[1]
    token_weights = build_token_weights(query, [hit.product.name for hit in hits[:5]])
    if not has_strong_title_match(query, top.product.name, token_weights):
        return False
    return (top.score - second.score) >= cfg.search_skip_rerank_gap
