from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProductData(BaseModel):
    name: str
    price: int
    colors: list[str]
    specs: list[str]
    description: str = ""
    image: str
    link: str
    score: float = 0.0


class ChatIncoming(BaseModel):
    message: str = Field(..., min_length=1)


class WebSocketMessage(BaseModel):
    type: Literal["message", "product", "status", "error", "done"]
    content: str | None = None
    data: ProductData | None = None


class RebuildResponse(BaseModel):
    status: str
    total_products: int
    message: str


class HealthResponse(BaseModel):
    status: str
