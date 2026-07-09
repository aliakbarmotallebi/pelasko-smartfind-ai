from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    products_api_url: str = Field(
        default="https://pelasko-morvarid.ir/api/products",
        alias="PRODUCTS_API_URL",
    )
    product_base_url: str = Field(
        default="https://pelasko-morvarid.ir",
        alias="PRODUCT_BASE_URL",
    )
    embedding_model: str = Field(
        default="xmanii/maux-gte-persian",
        alias="EMBEDDING_MODEL",
    )
    hakim_api_key: str = Field(default="mcinext", alias="HAKIM_API_KEY")
    hakim_api_base_url: str = Field(
        default="http://mcinext.ai/api",
        alias="HAKIM_API_BASE_URL",
    )
    hakim_timeout: int = Field(default=60, alias="HAKIM_TIMEOUT", ge=10)
    hakim_max_retries: int = Field(default=3, alias="HAKIM_MAX_RETRIES", ge=1, le=10)
    hakim_retry_delay: int = Field(default=2, alias="HAKIM_RETRY_DELAY", ge=1)
    data_dir: str = Field(default="data", alias="DATA_DIR")
    search_top_k: int = Field(default=10, alias="SEARCH_TOP_K", ge=1, le=20)
    display_top_k: int = Field(default=3, alias="DISPLAY_TOP_K", ge=1, le=3)
    search_min_score: float = Field(
        default=0.40,
        alias="SEARCH_MIN_SCORE",
        ge=0.0,
        le=1.0,
    )
    products_api_timeout: int = Field(default=60, alias="PRODUCTS_API_TIMEOUT", ge=5)

    index_rebuild_enabled: bool = Field(default=True, alias="INDEX_REBUILD_ENABLED")
    index_rebuild_interval_hours: int = Field(
        default=24,
        alias="INDEX_REBUILD_INTERVAL_HOURS",
        ge=1,
    )

    gapgpt_api_key: str = Field(default="", alias="GAPGPT_API_KEY")
    gapgpt_model: str = Field(default="gapgpt-qwen-3.5", alias="GAPGPT_MODEL")
    gapgpt_base_url: str = Field(
        default="https://api.gapgpt.app/v1",
        alias="GAPGPT_BASE_URL",
    )
    gapgpt_timeout: int = Field(default=120, alias="GAPGPT_TIMEOUT", ge=10)

    chat_log_enabled: bool = Field(default=True, alias="CHAT_LOG_ENABLED")
    chat_log_dir: str = Field(default="logs", alias="CHAT_LOG_DIR")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    public_host: str = Field(default="localhost", alias="PUBLIC_HOST")
    client_port: int = Field(default=5173, alias="CLIENT_PORT", ge=1)

    api_url: str = Field(default="", alias="API_URL")
    client_url: str = Field(default="", alias="CLIENT_URL")
    cors_origins: str = Field(default="", alias="CORS_ORIGINS")

    @property
    def index_path(self) -> str:
        return f"{self.data_dir.rstrip('/')}/index.faiss"

    @property
    def products_path(self) -> str:
        return f"{self.data_dir.rstrip('/')}/products.pkl"

    @property
    def gapgpt_enabled(self) -> bool:
        return bool(self.gapgpt_api_key.strip())

    @property
    def resolved_api_url(self) -> str:
        if self.api_url.strip():
            return self.api_url.strip().rstrip("/")
        return f"http://{self.public_host}:{self.port}"

    @property
    def resolved_client_url(self) -> str:
        if self.client_url.strip():
            return self.client_url.strip().rstrip("/")
        return f"http://{self.public_host}:{self.client_port}"

    @property
    def resolved_ws_url(self) -> str:
        return f"ws://{self.public_host}:{self.client_port}/ws/chat"

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip():
            return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        return [self.resolved_client_url]


@lru_cache
def get_settings() -> Settings:
    return Settings()
