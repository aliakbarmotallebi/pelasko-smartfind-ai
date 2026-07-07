from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import requests

from app.config import Settings, get_settings
from app.models import ProductData

logger = logging.getLogger(__name__)


def extract_color_names(colors: Any) -> list[str]:
    if not isinstance(colors, list):
        return []
    names: list[str] = []
    for color in colors:
        if isinstance(color, dict):
            name = color.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        elif isinstance(color, str) and color.strip():
            names.append(color.strip())
    return names


def extract_spec_lines(specs: Any) -> list[str]:
    if not isinstance(specs, list):
        return []
    lines: list[str] = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        label = str(spec.get("label", "")).strip()
        value = str(spec.get("value", "")).strip()
        if label and value:
            lines.append(f"{label} {value}")
        elif value:
            lines.append(value)
        elif label:
            lines.append(label)
    return lines


def build_searchable_text(product: dict[str, Any]) -> str:
    name = str(product.get("name", "")).strip()
    category = str(product.get("category", "")).strip()
    brand = str(product.get("brand", "")).strip()
    description = str(product.get("description", "")).strip()
    colors = extract_color_names(product.get("colors"))
    spec_lines = extract_spec_lines(product.get("specs"))

    parts: list[str] = [f"نام:\n{name}"]

    if category:
        parts.append(f"دسته‌بندی:\n{category}")

    if brand:
        parts.append(f"برند:\n{brand}")

    if colors:
        parts.append(f"رنگ:\n{'، '.join(colors)}")

    if spec_lines:
        parts.append("مشخصات:\n" + "\n".join(spec_lines))

    if description:
        parts.append(f"توضیحات:\n{description}")

    return "\n\n".join(parts)


def build_product_link(base_url: str, slug: str, product_id: str = "") -> str:
    base = base_url.rstrip("/")
    encoded_slug = quote(slug, safe="")
    if product_id.strip():
        encoded_id = quote(product_id.strip(), safe="")
        return f"{base}/products/{encoded_id}/{encoded_slug}"
    return f"{base}/products/{encoded_slug}"


def to_product_data(
    product: dict[str, Any],
    product_base_url: str,
    score: float = 0.0,
) -> ProductData:
    slug = str(product.get("slug", "")).strip()
    product_id = str(product.get("id", "")).strip()
    return ProductData(
        name=str(product.get("name", "")).strip(),
        price=int(product.get("price", 0) or 0),
        colors=extract_color_names(product.get("colors")),
        specs=extract_spec_lines(product.get("specs")),
        description=str(product.get("description", "")).strip(),
        image=str(product.get("image", "")).strip(),
        link=build_product_link(product_base_url, slug, product_id) if slug else "",
        score=round(score, 4),
    )


def normalize_products(
    products: list[dict[str, Any]],
    product_base_url: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for product in products:
        slug = str(product.get("slug", "")).strip()
        product_id = str(product.get("id", "")).strip()
        normalized.append(
            {
                "id": product_id,
                "name": str(product.get("name", "")).strip(),
                "slug": slug,
                "price": int(product.get("price", 0) or 0),
                "colors": extract_color_names(product.get("colors")),
                "specs": extract_spec_lines(product.get("specs")),
                "description": str(product.get("description", "")).strip(),
                "image": str(product.get("image", "")).strip(),
                "link": build_product_link(product_base_url, slug, product_id) if slug else "",
                "category": str(product.get("category", "")).strip(),
                "brand": str(product.get("brand", "")).strip(),
                "in_stock": bool(product.get("inStock", True)),
                "search_text": build_searchable_text(product),
            }
        )
    return normalized


def fetch_all_products(settings: Settings | None = None) -> list[dict[str, Any]]:
    cfg = settings or get_settings()
    logger.info("Fetching products from %s", cfg.products_api_url)

    try:
        response = requests.get(
            cfg.products_api_url,
            timeout=cfg.products_api_timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Failed to fetch products: %s", exc)
        raise RuntimeError(f"Failed to fetch products from {cfg.products_api_url}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Products API returned invalid JSON") from exc

    products = payload.get("products")
    if not isinstance(products, list):
        raise RuntimeError("Products API response missing 'products' list")

    total = payload.get("total", len(products))
    logger.info("Fetched %d products (total reported: %s)", len(products), total)
    return products


def format_products_for_prompt(products: list[ProductData]) -> str:
    blocks: list[str] = []
    for index, product in enumerate(products, start=1):
        colors = "، ".join(product.colors) if product.colors else "نامشخص"
        specs = "\n".join(f"- {spec}" for spec in product.specs) if product.specs else "- نامشخص"
        description = product.description.strip() if product.description else "نامشخص"
        score_text = f"{product.score:.2f}" if product.score else "نامشخص"
        blocks.append(
            "\n".join(
                [
                    f"محصول {index}:",
                    f"نام: {product.name}",
                    f"قیمت: {product.price:,} تومان",
                    f"رنگ‌ها: {colors}",
                    "مشخصات:",
                    specs,
                    f"توضیحات: {description}",
                    f"شباهت جستجو: {score_text}",
                ]
            )
        )
    return "\n\n".join(blocks)
