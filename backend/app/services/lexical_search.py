from __future__ import annotations

import math
import re
import unicodedata

_PERSIAN_CHAR_MAP = str.maketrans(
    {
        "ي": "ی",
        "ك": "ک",
        "ة": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "ٱ": "ا",
        "‌": " ",
    }
)

_STOPWORDS = frozenset(
    {
        "و",
        "در",
        "به",
        "از",
        "برای",
        "با",
        "یک",
        "یه",
        "می",
        "خوام",
        "میخوام",
        "میخواهم",
        "لطفا",
        "لطفاً",
        "من",
        "را",
        "رو",
        "که",
        "این",
        "آن",
        "است",
        "هست",
        "the",
        "a",
        "an",
    }
)


def normalize_persian(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text.strip().lower())
    normalized = normalized.translate(_PERSIAN_CHAR_MAP)
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def tokenize_query(text: str, *, min_length: int = 2) -> list[str]:
    tokens = normalize_persian(text).split()
    return [token for token in tokens if len(token) >= min_length and token not in _STOPWORDS]


def extract_latest_user_turn(message: str) -> str:
    matches = re.findall(
        r"کاربر:\s*(.+?)(?=\n(?:دستیار:|کاربر:)|\Z)",
        message,
        flags=re.DOTALL,
    )
    if matches:
        return matches[-1].strip()
    return message.strip()


def should_use_fast_query_extraction(message: str) -> bool:
    latest = extract_latest_user_turn(message)
    if latest != message.strip():
        return len(latest) <= 120
    return "\n" not in message and len(message) <= 120


def build_token_weights(query: str, product_names: list[str]) -> dict[str, float]:
    tokens = tokenize_query(query)
    if not tokens:
        return {}

    total_products = max(len(product_names), 1)
    weights: dict[str, float] = {}
    for token in tokens:
        document_frequency = sum(
            1 for name in product_names if token in normalize_persian(name)
        )
        if document_frequency == 0:
            continue
        weights[token] = math.log((total_products + 1) / (document_frequency + 1)) + 1.0
    return weights


def title_match_score(query: str, product_name: str, token_weights: dict[str, float]) -> float:
    if not token_weights:
        return 0.0

    name_norm = normalize_persian(product_name)
    matched_weight = sum(weight for token, weight in token_weights.items() if token in name_norm)
    total_weight = sum(token_weights.values())
    return matched_weight / total_weight if total_weight else 0.0


def has_strong_title_match(query: str, product_name: str, token_weights: dict[str, float]) -> bool:
    if not token_weights:
        return False

    name_norm = normalize_persian(product_name)
    matched_weights = [weight for token, weight in token_weights.items() if token in name_norm]
    if not matched_weights:
        return False

    return max(matched_weights) >= max(token_weights.values()) * 0.75
