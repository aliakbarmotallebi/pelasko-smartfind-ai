from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.models import ChatIncoming, ProductData, WebSocketMessage
from app.services.gapgpt import GapGPTClient
from app.services.search_engine import SearchEngine

logger = logging.getLogger(__name__)

router = APIRouter()


async def _send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    await websocket.send_json(payload)


async def _send_message(websocket: WebSocket, content: str) -> None:
    message = WebSocketMessage(type="message", content=content)
    await _send_json(websocket, message.model_dump(exclude_none=True))


async def _send_status(websocket: WebSocket, content: str) -> None:
    message = WebSocketMessage(type="status", content=content)
    await _send_json(websocket, message.model_dump(exclude_none=True))


async def _send_product(websocket: WebSocket, product: ProductData) -> None:
    message = WebSocketMessage(type="product", data=product)
    await _send_json(websocket, message.model_dump(exclude_none=True))


async def _send_error(websocket: WebSocket, content: str) -> None:
    message = WebSocketMessage(type="error", content=content)
    await _send_json(websocket, message.model_dump(exclude_none=True))


async def _send_done(websocket: WebSocket) -> None:
    message = WebSocketMessage(type="done")
    await _send_json(websocket, message.model_dump(exclude_none=True))


async def handle_chat_message(
    websocket: WebSocket,
    user_message: str,
    search_engine: SearchEngine,
    gapgpt_client: GapGPTClient,
) -> None:
    await _send_status(websocket, "دارم محصولات مناسب را بررسی می‌کنم...")

    search_query = await gapgpt_client.extract_search_query(user_message)
    products = await asyncio.to_thread(search_engine.search, search_query)

    if not products:
        await _send_message(
            websocket,
            "متأسفانه محصول مناسبی پیدا نکردم. لطفاً درخواست خود را دقیق‌تر بنویسید.",
        )
        await _send_done(websocket)
        return

    for product in products:
        await _send_product(websocket, product)

    async for token in gapgpt_client.stream_sales_response(user_message, products):
        if token:
            await _send_message(websocket, token)

    await _send_done(websocket)


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket) -> None:
    search_engine: SearchEngine | None = getattr(websocket.app.state, "search_engine", None)
    gapgpt_client: GapGPTClient | None = getattr(websocket.app.state, "gapgpt_client", None)

    if search_engine is None or gapgpt_client is None:
        await websocket.close(code=1011, reason="Service not initialized")
        return

    await websocket.accept()
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info("WebSocket connected: %s", client_host)

    try:
        while True:
            raw_payload = await websocket.receive_json()
            try:
                incoming = ChatIncoming.model_validate(raw_payload)
            except Exception:
                await _send_error(websocket, "فرمت پیام نامعتبر است. فیلد message الزامی است.")
                await _send_done(websocket)
                continue

            logger.info("Received chat message from %s", client_host)
            try:
                await handle_chat_message(
                    websocket,
                    incoming.message.strip(),
                    search_engine,
                    gapgpt_client,
                )
            except Exception as exc:
                logger.exception("Chat handling failed: %s", exc)
                await _send_error(websocket, "خطایی در پردازش پیام رخ داد. لطفاً دوباره تلاش کنید.")
                await _send_done(websocket)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", client_host)
    except Exception as exc:
        logger.exception("WebSocket error: %s", exc)
        try:
            await _send_error(websocket, "اتصال با خطا مواجه شد.")
            await _send_done(websocket)
        except Exception:
            pass
