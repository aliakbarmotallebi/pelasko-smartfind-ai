from __future__ import annotations

import logging
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

SALES_SYSTEM_PROMPT = (
    "تو یک دستیار فروش حرفه‌ای فارسی هستی. "
    "پاسخ را محترمانه، دوستانه و فروشگاهی بنویس. "
    "فقط بر اساس محصولات داده‌شده پاسخ بده و اطلاعات جعلی نساز."
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

    def _build_sales_prompt(self, user_message: str, products: list[ProductData]) -> str:
        products_text = format_products_for_prompt(products)
        return (
            f"کاربر:\n{user_message}\n\n"
            f"محصولات موجود:\n{products_text}\n\n"
            "وظیفه:\n"
            "بهترین محصول را پیشنهاد بده.\n\n"
            "پاسخ باید شامل:\n"
            "- نام محصول\n"
            "- دلیل پیشنهاد\n"
            "- رنگ‌ها\n"
            "- مشخصات مهم\n"
            "- قیمت\n"
            "- لینک خرید\n\n"
            "لحن:\n"
            "محترمانه، دوستانه و فروشگاهی"
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
        try:
            stream = await self._client.chat.completions.create(
                model=self._settings.gapgpt_model,
                temperature=0.7,
                stream=True,
                messages=[
                    {"role": "system", "content": SALES_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            logger.exception("GapGPT streaming failed: %s", exc)
            yield self._fallback_response(user_message, products)

    def _fallback_response(self, user_message: str, products: list[ProductData]) -> str:
        if not products:
            return (
                "متأسفانه محصول مناسبی برای درخواست شما پیدا نکردم. "
                "لطفاً با جزئیات بیشتری دوباره امتحان کنید."
            )

        best = products[0]
        colors = "، ".join(best.colors) if best.colors else "نامشخص"
        specs = " | ".join(best.specs[:3]) if best.specs else "نامشخص"
        return (
            f"سلام! برای درخواست «{user_message}»، محصول «{best.name}» را پیشنهاد می‌کنم.\n"
            f"قیمت: {best.price:,} تومان\n"
            f"رنگ‌ها: {colors}\n"
            f"مشخصات: {specs}\n"
            f"لینک خرید: {best.link}"
        )
