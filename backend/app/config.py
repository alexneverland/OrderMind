from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    APP_ENV: str = Field(default="development", description="Environment mode")
    APP_DEBUG: bool = Field(default=False, description="Debug mode")
    PORT: int = Field(default=8000, description="Server port")
    HOST: str = Field(default="0.0.0.0", description="Server host")

    # Local database: SQLite
    DATABASE_URL: str = Field(
        default="sqlite:///./ordermind.db",
        description="Database connection URL"
    )

    # AI Provider settings (abstracted)
    AI_PROVIDER: str = Field(default="mock", description="Active AI provider: mock, gemini, openai, vertex, anthropic")
    AI_MODEL: str = Field(default="mock-model", description="AI model name")

    # API keys and Cloud credentials (loaded from .env only, never committed)
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_CLOUD_PROJECT: Optional[str] = None
    GOOGLE_CLOUD_LOCATION: Optional[str] = "us-central1"

    # Input validation limits
    MAX_RAW_ORDER_TEXT_SIZE: int = Field(default=50000, description="Max raw text size in characters")
    MAX_ORDER_LINES: int = Field(default=500, description="Max lines allowed per order")
    MAX_IMPORT_UPLOAD_SIZE_BYTES: int = Field(default=10_000_000, description="Maximum Excel upload size")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
