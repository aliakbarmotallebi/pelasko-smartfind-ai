from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings, get_settings
from app.indexing.loader import format_products_for_prompt
from app.models import ProductData
from app.services.lexical_search import (
    extract_latest_user_turn,
    should_use_fast_query_extraction,
)

logger = logging.getLogger(__name__)

INTENT_SYSTEM_PROMPT = (
    "از آخرین پیام کاربر فقط یک عبارت جستجوی کوتاه فارسی برای یافتن محصول استخراج کن. "
    "فقط همان عبارت را بنویس."
)

RERANK_SYSTEM_PROMPT = (
    "شماره بهترین محصول را برای درخواست کاربر انتخاب کن. "
    "محصول باید با نوع کالا (مثلاً کلمن، قابلمه) همخوان باشد، نه فقط واژه‌های توصیفی مثل کوچک. "
    "اگر هیچ‌کدام مناسب نیست فقط 0 بنویس. فقط یک عدد."
)

SALES_SYSTEM_PROMPT = (
    "تو یک دستیار فروش فارسی هستی. "
    "حداکثر ۲ جمله کوتاه بنویس. "
    "فقط از نام، قیمت، رنگ‌ها، مشخصات و توضیحات داده‌شده استفاده کن. "
    "هرگز کاربرد، مناسب سفر، روزمره، مسافرتی یا ویژگی‌ای که در داده نیست ننویس. "
    "اگر specs یا description خالی یا نامشخص است، فقط نام، قیمت و رنگ را بگو. "
    "لینک ننویس."
)


class GapGPTClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = AsyncOpenAI(
            api_key=self._settings.gapgpt_api_key,
            base_url=self._settings.gapgpt_base_url,
            timeout=self._settings.gapgpt_timeout,
        )

    @property
    def enabled(self) -> bool:
        return self._settings.gapgpt_enabled

    async def extract_search_query(self, user_message: str) -> tuple[str, dict[str, Any]]:
        latest_turn = extract_latest_user_turn(user_message)
        if should_use_fast_query_extraction(user_message):
            logger.info("Fast query extraction: %s", latest_turn)
            return latest_turn, {"method": "fast", "input": user_message}

        if not self.enabled:
            return latest_turn, {"method": "fallback", "input": user_message}

        try:
            response = await self._client.chat.completions.create(
                model=self._settings.gapgpt_model,
                temperature=0.0,
                max_tokens=32,
                messages=[
                    {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
            content = response.choices[0].message.content
            query = content.strip() if content else latest_turn
            logger.info("Extracted search query: %s", query)
            return query or latest_turn, {
                "method": "llm",
                "input": user_message,
                "latest_turn": latest_turn,
            }
        except Exception as exc:
            logger.warning("Intent extraction failed, using latest user turn: %s", exc)
            return latest_turn, {
                "method": "fallback",
                "input": user_message,
                "reason": str(exc),
            }

    async def pick_best_product(
        self,
        search_query: str,
        products: list[ProductData],
        *,
        skip: bool = False,
    ) -> tuple[ProductData | None, dict[str, Any]]:
        if not products:
            return None, {"raw_response": "", "picked_index": 0, "used_fallback": True}

        if skip or len(products) == 1:
            return products[0], {
                "raw_response": "",
                "picked_index": 1,
                "used_fallback": True,
                "reason": "skip_rerank",
            }

        if not self.enabled:
            return products[0], {
                "raw_response": "",
                "picked_index": 1,
                "used_fallback": True,
                "reason": "gapgpt_disabled",
            }

        prompt = (
            f"درخواست:\n{search_query}\n\n"
            f"محصولات:\n{format_products_for_prompt(products)}\n\n"
            "شماره بهترین محصول:"
        )

        try:
            response = await self._client.chat.completions.create(
                model=self._settings.gapgpt_model,
                temperature=0.0,
                max_tokens=8,
                messages=[
                    {"role": "system", "content": RERANK_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            content = response.choices[0].message.content or ""
            picked = self._parse_product_index(content, len(products))
            if picked == 0:
                logger.info("Rerank rejected all products for: %s", search_query)
                return None, {
                    "raw_response": content,
                    "picked_index": 0,
                    "used_fallback": False,
                    "prompt": prompt,
                }
            selected = products[picked - 1]
            logger.info("Rerank picked product %d: %s", picked, selected.name)
            return selected, {
                "raw_response": content,
                "picked_index": picked,
                "used_fallback": False,
                "prompt": prompt,
            }
        except Exception as exc:
            logger.warning("Product rerank failed, using top search result: %s", exc)
            return products[0], {
                "raw_response": "",
                "picked_index": 1,
                "used_fallback": True,
                "reason": str(exc),
                "prompt": prompt,
            }

    @staticmethod
    def _parse_product_index(content: str, total: int) -> int:
        match = re.search(r"\b(\d+)\b", content.strip())
        if not match:
            return 1
        index = int(match.group(1))
        if index == 0:
            return 0
        if 1 <= index <= total:
            return index
        return 1

    @staticmethod
    def _product_has_rich_details(product: ProductData) -> bool:
        return bool(product.specs) or bool(product.description.strip())

    @staticmethod
    def build_template_sales_response(search_query: str, product: ProductData) -> str:
        colors = f" — رنگ: {'، '.join(product.colors)}" if product.colors else ""
        specs = " — ".join(product.specs[:2]) if product.specs else ""
        description = product.description.strip()

        if specs:
            detail = f" مشخصات: {specs}."
        elif description:
            detail = f" {description}."
        else:
            detail = "."

        return (
            f"برای «{search_query}»، «{product.name}» را پیشنهاد می‌کنم"
            f"{colors} — قیمت: {product.price:,} تومان{detail}"
        )

    def _build_sales_prompt(self, search_query: str, products: list[ProductData]) -> str:
        products_text = format_products_for_prompt(products)
        return (
            f"درخواست:\n{search_query}\n\n"
            f"محصول:\n{products_text}\n\n"
            "فقط نام، قیمت، رنگ و اطلاعات موجود در داده را در ۱-۲ جمله بگو."
        )

    async def stream_sales_response(
        self,
        search_query: str,
        products: list[ProductData],
    ) -> AsyncIterator[str]:
        if not products:
            yield (
                "متأسفانه محصول مناسبی برای درخواست شما پیدا نکردم. "
                "لطفاً با جزئیات بیشتری دوباره امتحان کنید."
            )
            return

        product = products[0]
        if self._settings.gapgpt_fast_sales_template and not self._product_has_rich_details(
            product
        ):
            yield self.build_template_sales_response(search_query, product)
            return

        if not self.enabled:
            yield self.build_template_sales_response(search_query, product)
            return

        prompt = self._build_sales_prompt(search_query, products)
        streamed = False
        try:
            stream = await self._client.chat.completions.create(
                model=self._settings.gapgpt_model,
                temperature=0.1,
                max_tokens=120,
                stream=True,
                messages=[
                    {"role": "system", "content": SALES_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    streamed = True
                    yield delta
        except Exception as exc:
            logger.exception("GapGPT streaming failed: %s", exc)
            if not streamed:
                yield self.build_template_sales_response(search_query, product)
