from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.config import Settings, get_settings
from app.indexing.loader import format_products_for_prompt
from app.models import ProductData

logger = logging.getLogger(__name__)

INTENT_SYSTEM_PROMPT = (
    "تو یک دستیار فروشگاه آنلاین فارسی هستی. "
    "از پیام کاربر فقط یک عبارت جستجوی کوتاه و دقیق فارسی برای یافتن محصول استخراج کن. "
    "فقط همان عبارت جستجو را بنویس، بدون توضیح اضافه."
)

RERANK_SYSTEM_PROMPT = (
    "تو یک دستیار فروشگاه آنلاین فارسی هستی. "
    "از میان محصولات داده‌شده، شماره بهترین محصول مناسب برای درخواست کاربر را انتخاب کن. "
    "محصول باید واقعاً با نیاز کاربر مرتبط باشد، نه فقط شباهت ظاهری. "
    "اگر هیچ محصولی واقعاً مناسب نیست، فقط عدد 0 را بنویس. "
    "فقط یک عدد بنویس، بدون هیچ توضیح اضافه."
)

SALES_SYSTEM_PROMPT = (
    "تو یک دستیار فروش حرفه‌ای فارسی هستی. "
    "پاسخ را کوتاه (حداکثر ۳-۴ جمله)، محترمانه و دوستانه بنویس. "
    "فقط بر اساس محصولات داده‌شده پاسخ بده و اطلاعات جعلی نساز. "
    "هرگز لینک، URL یا آدرس اینترنتی در پاسخ ننویس. "
    "از لیست‌بندی، بولت‌پوینت و ایموجی زیاد خودداری کن. "
    "اگر محصول داده‌شده با درخواست کاربر مرتبط نیست، صادقانه بگو محصول مناسبی موجود نیست."
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

    async def extract_search_query(self, user_message: str) -> str:
        if not self.enabled:
            return user_message.strip()

        try:
            response = await self._client.chat.completions.create(
                model=self._settings.gapgpt_model,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
            content = response.choices[0].message.content
            query = content.strip() if content else user_message.strip()
            logger.info("Extracted search query: %s", query)
            return query or user_message.strip()
        except Exception as exc:
            logger.warning("Intent extraction failed, using original message: %s", exc)
            return user_message.strip()

    async def pick_best_product(
        self,
        user_message: str,
        products: list[ProductData],
    ) -> ProductData | None:
        if not products:
            return None

        if not self.enabled:
            return products[0]

        prompt = (
            f"درخواست کاربر:\n{user_message}\n\n"
            f"محصولات:\n{format_products_for_prompt(products)}\n\n"
            "شماره بهترین محصول را بنویس (یا 0 اگر هیچ‌کدام مناسب نیست):"
        )

        try:
            response = await self._client.chat.completions.create(
                model=self._settings.gapgpt_model,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": RERANK_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            content = response.choices[0].message.content or ""
            picked = self._parse_product_index(content, len(products))
            if picked == 0:
                logger.info("Rerank rejected all products for: %s", user_message)
                return None
            selected = products[picked - 1]
            logger.info("Rerank picked product %d: %s", picked, selected.name)
            return selected
        except Exception as exc:
            logger.warning("Product rerank failed, using top search result: %s", exc)
            return products[0]

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

    def _build_sales_prompt(self, user_message: str, products: list[ProductData]) -> str:
        products_text = format_products_for_prompt(products)
        return (
            f"کاربر:\n{user_message}\n\n"
            f"محصولات موجود:\n{products_text}\n\n"
            "وظیفه:\n"
            "بهترین محصول را در ۲-۴ جمله کوتاه پیشنهاد بده.\n\n"
            "پاسخ باید شامل:\n"
            "- نام محصول\n"
            "- یک دلیل کوتاه برای پیشنهاد\n"
            "- رنگ (در صورت وجود)\n"
            "- قیمت\n\n"
            "مهم:\n"
            "- لینک یا URL ننویس\n"
            "- مشخصات را خلاصه در یک جمله بگو، نه لیست\n"
            "- لحن: محترمانه، دوستانه و فروشگاهی"
        )

    async def stream_sales_response(
        self,
        user_message: str,
        products: list[ProductData],
    ) -> AsyncIterator[str]:
        if not self.enabled:
            yield self._fallback_response(user_message, products)
            return

        prompt = self._build_sales_prompt(user_message, products)
        streamed = False
        try:
            stream = await self._client.chat.completions.create(
                model=self._settings.gapgpt_model,
                temperature=0.4,
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
                yield self._fallback_response(user_message, products)

    def _fallback_response(self, user_message: str, products: list[ProductData]) -> str:
        if not products:
            return (
                "متأسفانه محصول مناسبی برای درخواست شما پیدا نکردم. "
                "لطفاً با جزئیات بیشتری دوباره امتحان کنید."
            )

        best = products[0]
        colors = f" · رنگ: {'، '.join(best.colors)}" if best.colors else ""
        return (
            f"برای «{user_message}»، «{best.name}» را پیشنهاد می‌کنم. "
            f"قیمت: {best.price:,} تومان{colors}."
        )
