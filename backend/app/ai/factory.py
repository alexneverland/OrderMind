from typing import Optional, Dict, Type
from backend.app.ai.base import BaseAIProvider
from backend.app.ai.mock_provider import MockAIProvider
from backend.app.ai.gemini_provider import GeminiProvider
from backend.app.ai.stubs import OpenAIProvider, AnthropicProvider, VertexProvider
from backend.app.config import settings

PROVIDER_MAP: Dict[str, Type[BaseAIProvider]] = {
    "mock": MockAIProvider,
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "vertex": VertexProvider,
}


def get_ai_provider(provider_name: Optional[str] = None) -> BaseAIProvider:
    """
    Factory function returning the configured AI Provider instance.
    Decouples callers from specific provider classes.
    """
    selected = (provider_name or settings.AI_PROVIDER or "mock").strip().lower()

    provider_cls = PROVIDER_MAP.get(selected)
    if not provider_cls:
        raise ValueError(
            f"Unsupported AI provider: '{selected}'. "
            f"Supported providers are: {list(PROVIDER_MAP.keys())}"
        )

    return provider_cls()
