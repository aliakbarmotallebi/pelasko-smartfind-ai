from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.models import ChatIncoming, ProductData, WebSocketMessage
from app.services.chat_logger import (
    build_embedding_log,
    build_search_log,
    get_chat_logger,
)
from app.services.gapgpt import GapGPTClient
from app.services.search_engine import SearchEngine

logger = logging.getLogger(__name__)

router = APIRouter()


class ClientDisconnectedError(Exception):
    pass


async def _send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await websocket.send_json(payload)
    except (WebSocketDisconnect, RuntimeError) as exc:
        if isinstance(exc, WebSocketDisconnect):
            raise ClientDisconnectedError from exc
        if "close message" in str(exc).lower():
            raise ClientDisconnectedError from exc
        raise


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


def _product_key(product: ProductData) -> str:
    return product.link or product.name


def _products_for_display(
    candidates: list[ProductData],
    picked: ProductData | None,
    limit: int,
) -> list[ProductData]:
    seen: set[str] = set()
    display: list[ProductData] = []

    if picked is not None:
        display.append(picked)
        seen.add(_product_key(picked))

    for product in candidates:
        if len(display) >= limit:
            break
        key = _product_key(product)
        if key in seen:
            continue
        display.append(product)
        seen.add(key)

    return display


async def handle_chat_message(
    websocket: WebSocket,
    user_message: str,
    search_engine: SearchEngine,
    gapgpt_client: GapGPTClient,
    *,
    client_host: str = "unknown",
) -> None:
    chat_logger = get_chat_logger()
    trace = chat_logger.new_trace(client_host=client_host, user_message=user_message)
    sent_statuses: list[str] = []
    sent_messages: list[str] = []
    sent_products: list[dict] = []
    sent_errors: list[str] = []

    try:
        await _send_status(websocket, "دارم محصولات مناسب را بررسی می‌کنم...")
        sent_statuses.append("دارم محصولات مناسب را بررسی می‌کنم...")

        search_query = await gapgpt_client.extract_search_query(user_message)
        trace.llm_query_extraction = {
            "input": user_message,
            "output": search_query,
            "model": get_settings().gapgpt_model,
        }

        search_details = await asyncio.to_thread(
            search_engine.search_with_details,
            search_query,
        )
        candidates = search_details.results

        trace.embedding = build_embedding_log(
            query=search_details.query,
            model_name=search_details.embedding_model,
            vector=search_details.embedding_vector,
        )
        trace.search = build_search_log(
            query=search_details.query,
            min_score=search_details.min_score,
            top_k=search_details.top_k,
            hits=[
                {
                    "rank": index + 1,
                    "score": round(hit.score, 6),
                    "passed_min_score": hit.passed_min_score,
                    "in_stock": hit.in_stock,
                    "product": hit.product.model_dump(),
                }
                for index, hit in enumerate(search_details.hits)
            ],
            results=candidates,
        )

        if not candidates:
            no_result_message = (
                "متأسفانه محصول مناسبی پیدا نکردم. لطفاً درخواست خود را دقیق‌تر بنویسید."
            )
            await _send_message(websocket, no_result_message)
            sent_messages.append(no_result_message)
            trace.sent_to_user = {
                "statuses": sent_statuses,
                "messages": sent_messages,
                "products": sent_products,
                "errors": sent_errors,
            }
            await _send_done(websocket)
            return

        picked, rerank_meta = await gapgpt_client.pick_best_product(user_message, candidates)
        trace.llm_rerank = {
            **rerank_meta,
            "picked_product": picked.model_dump() if picked else None,
        }

        display_limit = get_settings().display_top_k
        display_products = _products_for_display(candidates, picked, display_limit)

        if picked is None:
            picked = candidates[0]

        for product in display_products:
            await _send_product(websocket, product)
            sent_products.append(product.model_dump())

        sales_tokens: list[str] = []
        async for token in gapgpt_client.stream_sales_response(user_message, [picked]):
            if token:
                sales_tokens.append(token)
                await _send_message(websocket, token)

        sales_response = "".join(sales_tokens)
        trace.llm_sales = {
            "model": get_settings().gapgpt_model,
            "input_user_message": user_message,
            "input_products": [picked.model_dump()],
            "output": sales_response,
            "streamed_tokens": sales_tokens,
        }
        sent_messages.extend(sales_tokens)

        trace.sent_to_user = {
            "statuses": sent_statuses,
            "messages": sent_messages,
            "full_message": sales_response,
            "products": sent_products,
            "errors": sent_errors,
        }
        await _send_done(websocket)
    except Exception as exc:
        trace.error = str(exc)
        raise
    finally:
        chat_logger.save(trace)


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
                    client_host=client_host,
                )
            except ClientDisconnectedError:
                logger.info("Client disconnected during chat handling: %s", client_host)
                return
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected during chat handling: %s", client_host)
                return
            except Exception as exc:
                logger.exception("Chat handling failed: %s", exc)
                try:
                    await _send_error(websocket, "خطایی در پردازش پیام رخ داد. لطفاً دوباره تلاش کنید.")
                    await _send_done(websocket)
                except (ClientDisconnectedError, WebSocketDisconnect):
                    return

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", client_host)
    except Exception as exc:
        logger.exception("WebSocket error: %s", exc)
        try:
            await _send_error(websocket, "اتصال با خطا مواجه شد.")
            await _send_done(websocket)
        except (ClientDisconnectedError, WebSocketDisconnect, RuntimeError):
            pass
