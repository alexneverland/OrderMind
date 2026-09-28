from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    APP_ENV: str = Field(default="development", description="Environment mode")
    APP_DEBUG: bool = Field(default=True, description="Debug mode")
    PORT: int = Field(default=8000, description="Server port")
    HOST: str = Field(default="0.0.0.0", description="Server host")

    # Database: SQLite by default for development, ready for PostgreSQL/MySQL
    DATABASE_URL: str = Field(
        default="sqlite:///./ordermind.db",
        description="Database connection URL"
    )

    # AI Provider settings (abstracted)
    AI_PROVIDER: str = Field(default="mock", description="Active AI provider: mock, gemini, openai, vertex, anthropic")
    AI_MODEL: str = Field(default="mock-model", description="AI model name")

    # API keys (loaded from .env only, never committed)
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
