from __future__ import annotations

import logging
import time
from typing import Protocol

import numpy as np
import requests
from sentence_transformers import SentenceTransformer

from app.config import Settings

logger = logging.getLogger(__name__)

HAKIM_MODEL_IDS = {
    "mcinext/hakim": "hakim",
    "hakim": "hakim",
    "mcinext/hakim-small": "hakim-small",
    "hakim-small": "hakim-small",
    "mcinext/hakim-unsup": "hakim-unsup",
    "hakim-unsup": "hakim-unsup",
}

HAKIM_API_MODEL_NAMES = {
    "hakim": "Hakim",
    "hakim-small": "Hakim_small",
    "hakim-unsup": "Hakim_unsuper",
}

RETRIEVAL_PROMPT = "تشخیص ارتباط , آیا متن دوم به متن اول مرتبط است ؟"


class EmbeddingBackend(Protocol):
    @property
    def model_name(self) -> str: ...

    def encode_passages(
        self,
        texts: list[str],
        *,
        batch_size: int = 32,
        show_progress_bar: bool = False,
    ) -> np.ndarray: ...

    def encode_queries(
        self,
        texts: list[str],
        *,
        normalize_embeddings: bool = True,
    ) -> np.ndarray: ...


def is_hakim_model(model_name: str) -> bool:
    return model_name.strip().lower() in HAKIM_MODEL_IDS


def normalize_vectors(embeddings: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return embeddings / norms


class SentenceTransformerBackend:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: SentenceTransformer | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load_model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading embedding model: %s", self._model_name)
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def encode_passages(
        self,
        texts: list[str],
        *,
        batch_size: int = 32,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        model = self._load_model()
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress_bar,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return _as_2d_array(embeddings)

    def encode_queries(
        self,
        texts: list[str],
        *,
        normalize_embeddings: bool = True,
    ) -> np.ndarray:
        model = self._load_model()
        embeddings = model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=normalize_embeddings,
        )
        return _as_2d_array(embeddings)


class HakimBackend:
    def __init__(self, settings: Settings) -> None:
        variant = HAKIM_MODEL_IDS[settings.embedding_model.strip().lower()]
        self._variant = variant
        self._model_name = settings.embedding_model.strip()
        self._api_key = settings.hakim_api_key.strip()
        self._api_base_url = settings.hakim_api_base_url.rstrip("/")
        self._max_retries = settings.hakim_max_retries
        self._retry_delay = settings.hakim_retry_delay
        self._timeout = settings.hakim_timeout
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    @property
    def model_name(self) -> str:
        return self._model_name

    def _preprocess(self, text: str, *, role: str) -> str:
        if self._variant == "hakim-unsup":
            return text

        if self._variant == "hakim":
            return text

        task_prompt = f"مسئله : {RETRIEVAL_PROMPT}"
        if role == "query":
            return f"{task_prompt} | متن اول : {text}"
        return f"{task_prompt} | متن دوم : {text}"

    def _build_request(self, texts: list[str], *, role: str) -> tuple[str, dict]:
        if self._variant == "hakim":
            prompt_type = "retrieval.query" if role == "query" else "retrieval.passage"
            return f"{self._api_base_url}/embedding-model", {
                "model": HAKIM_API_MODEL_NAMES[self._variant],
                "input": texts,
                "prompt_type": prompt_type,
            }

        processed = [self._preprocess(text, role=role) for text in texts]
        return f"{self._api_base_url}/{self._variant}", {
            "model": HAKIM_API_MODEL_NAMES[self._variant],
            "input": processed,
            "encoding_format": "float",
            "add_special_tokens": True,
        }

    def _request_embeddings(self, texts: list[str], *, role: str) -> list[list[float]]:
        if not texts:
            return []

        url, payload = self._build_request(texts, role=role)
        for attempt in range(self._max_retries):
            try:
                response = requests.post(
                    url,
                    headers=self._headers,
                    json=payload,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                data = response.json()
                items = data.get("data")
                if not isinstance(items, list) or not items:
                    raise RuntimeError(f"Invalid Hakim API response: {data}")

                embeddings: list[list[float]] = []
                for item in items:
                    if isinstance(item, dict) and "embedding" in item:
                        embeddings.append(item["embedding"])
                    elif isinstance(item, list):
                        embeddings.append(item)
                    else:
                        raise RuntimeError(f"Unexpected embedding item: {item}")

                if len(embeddings) != len(texts):
                    raise RuntimeError(
                        f"Hakim API returned {len(embeddings)} embeddings for {len(texts)} inputs"
                    )
                return embeddings
            except requests.RequestException as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                logger.warning(
                    "Hakim API request failed (attempt %s/%s, status=%s): %s",
                    attempt + 1,
                    self._max_retries,
                    status_code,
                    exc,
                )
                if status_code is not None and 400 <= status_code < 500 and status_code != 429:
                    raise RuntimeError(f"Hakim API client error: {exc}") from exc
                if attempt + 1 >= self._max_retries:
                    raise RuntimeError(f"Hakim API failed after {self._max_retries} attempts") from exc
                time.sleep(self._retry_delay * (2**attempt))

        raise RuntimeError("Hakim API failed unexpectedly")

    def _encode(
        self,
        texts: list[str],
        *,
        role: str,
        batch_size: int = 32,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        del show_progress_bar  # Hakim API has no local progress bar.

        all_embeddings: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            all_embeddings.extend(self._request_embeddings(batch, role=role))

        array = np.array(all_embeddings, dtype=np.float32)
        return normalize_vectors(array)

    def encode_passages(
        self,
        texts: list[str],
        *,
        batch_size: int = 32,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        return self._encode(texts, role="passage", batch_size=batch_size, show_progress_bar=show_progress_bar)

    def encode_queries(
        self,
        texts: list[str],
        *,
        normalize_embeddings: bool = True,
    ) -> np.ndarray:
        del normalize_embeddings
        return self._encode(texts, role="query", batch_size=32)


def _as_2d_array(embeddings: np.ndarray | list[list[float]]) -> np.ndarray:
    array = np.asarray(embeddings, dtype=np.float32)
    if array.ndim != 2:
        raise RuntimeError("Embedding model returned unexpected output shape")
    return array


def create_embedding_backend(settings: Settings) -> EmbeddingBackend:
    if is_hakim_model(settings.embedding_model):
        if not settings.hakim_api_key.strip():
            raise RuntimeError("HAKIM_API_KEY is required when using a Hakim embedding model")
        logger.info("Using Hakim embedding API for model: %s", settings.embedding_model)
        return HakimBackend(settings)

    return SentenceTransformerBackend(settings.embedding_model)
