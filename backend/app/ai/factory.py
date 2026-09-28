from typing import Optional, Dict, Type, Set
from backend.app.ai.base import BaseAIProvider
from backend.app.ai.mock_provider import MockAIProvider
from backend.app.ai.gemini_provider import GeminiProvider
from backend.app.ai.stubs import OpenAIProvider, AnthropicProvider, VertexProvider
from backend.app.config import settings

# Explicit provider capability classification
IMPLEMENTED_PROVIDERS: Set[str] = {"mock", "gemini"}
PLANNED_PROVIDERS: Set[str] = {"openai", "anthropic", "vertex"}

PROVIDER_MAP: Dict[str, Type[BaseAIProvider]] = {
    "mock": MockAIProvider,
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "vertex": VertexProvider,
}

PROVIDER_STATUS: Dict[str, str] = {
    "mock": "implemented",
    "gemini": "implemented",
    "openai": "planned",
    "anthropic": "planned",
    "vertex": "planned",
}


def get_ai_provider(provider_name: Optional[str] = None) -> BaseAIProvider:
    """
    Factory function returning an implemented AI Provider instance.
    Enforces a strict distinction between implemented and planned providers.
    """
    selected = (provider_name or settings.AI_PROVIDER or "mock").strip().lower()

    if selected in PLANNED_PROVIDERS:
        raise NotImplementedError(
            f"AI provider '{selected}' is planned for a future release and is not yet implemented. "
            f"Currently implemented providers: {sorted(list(IMPLEMENTED_PROVIDERS))}"
        )

    if selected not in IMPLEMENTED_PROVIDERS:
        raise ValueError(
            f"Unknown AI provider: '{selected}'. "
            f"Implemented: {sorted(list(IMPLEMENTED_PROVIDERS))}, "
            f"Planned: {sorted(list(PLANNED_PROVIDERS))}"
        )

    provider_cls = PROVIDER_MAP[selected]
    return provider_cls()
