from typing import List, Optional, Dict, Any
from backend.app.ai.base import BaseAIProvider
from backend.app.schemas.adapters import NormalizedInput
from backend.app.schemas.order import NormalizedOrderLineDraft


class OpenAIProvider(BaseAIProvider):
    name: str = "openai"

    async def extract_order(
        self,
        normalized_input: NormalizedInput,
        context: Optional[Dict[str, Any]] = None
    ) -> List[NormalizedOrderLineDraft]:
        raise NotImplementedError("OpenAIProvider is planned for a future milestone.")


class AnthropicProvider(BaseAIProvider):
    name: str = "anthropic"

    async def extract_order(
        self,
        normalized_input: NormalizedInput,
        context: Optional[Dict[str, Any]] = None
    ) -> List[NormalizedOrderLineDraft]:
        raise NotImplementedError("AnthropicProvider is planned for a future milestone.")


class VertexProvider(BaseAIProvider):
    name: str = "vertex"

    async def extract_order(
        self,
        normalized_input: NormalizedInput,
        context: Optional[Dict[str, Any]] = None
    ) -> List[NormalizedOrderLineDraft]:
        raise NotImplementedError("VertexProvider is planned for a future milestone.")
