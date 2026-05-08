import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PG_")

    host: str = "localhost"
    port: int = 5432
    db: str = "stock_hawk"
    user: str = "stock_hawk"
    password: str = "stock_hawk_dev"

    @property
    def async_url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"


class Neo4jSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEO4J_")

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "stock_hawk_dev"


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_")

    url: str = "redis://localhost:6379/0"


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    custom_api_key: str = ""
    custom_base_url: str = ""
    custom_model: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    claude_api_key: str = ""
    deepseek_api_key: str = ""


class DataSourceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    tushare_token: str = ""
    eastmoney_cookie: str = ""
    eastmoney_user_agent: str = ""
    market_proxy_url: str = ""
    market_request_timeout: int = 15


class FeishuSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FEISHU_")

    webhook_url: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = "INFO"
    data_dir: Path = Path("./data")

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    data_source: DataSourceSettings = Field(default_factory=DataSourceSettings)
    feishu: FeishuSettings = Field(default_factory=FeishuSettings)


RUNTIME_SETTINGS_PATH = Path("./data/runtime_settings.json")


def load_runtime_settings() -> dict[str, Any]:
    if not RUNTIME_SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(RUNTIME_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def apply_runtime_settings(settings: Settings) -> Settings:
    runtime = load_runtime_settings()
    if not runtime:
        return settings

    llm_fields = {
        "custom_api_key",
        "custom_base_url",
        "custom_model",
        "deepseek_api_key",
        "openai_api_key",
        "openai_base_url",
        "claude_api_key",
    }
    for field_name in llm_fields:
        value = runtime.get(field_name)
        if value:
            setattr(settings.llm, field_name, value)

    data_source_fields = {
        "tushare_token",
        "eastmoney_cookie",
        "eastmoney_user_agent",
        "market_proxy_url",
        "market_request_timeout",
    }
    for field_name in data_source_fields:
        value = runtime.get(field_name)
        if value not in (None, ""):
            setattr(settings.data_source, field_name, value)
    if runtime.get("feishu_webhook_url"):
        settings.feishu.webhook_url = runtime["feishu_webhook_url"]
    if runtime.get("log_level"):
        settings.log_level = runtime["log_level"]
    return settings


@lru_cache
def get_settings() -> Settings:
    return apply_runtime_settings(Settings())
