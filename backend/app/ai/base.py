from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from backend.app.schemas.adapters import NormalizedInput
from backend.app.schemas.order import NormalizedOrderLineDraft


class BaseAIProvider(ABC):
    """
    Abstract interface for AI Providers.
    Decouples business logic and extraction from specific LLM providers.
    """
    name: str = "base"

    @abstractmethod
    async def extract_order(
        self,
        normalized_input: NormalizedInput,
        context: Optional[Dict[str, Any]] = None
    ) -> List[NormalizedOrderLineDraft]:
        """
        Extract line items from normalized input.
        Must return structured NormalizedOrderLineDraft list.
        """
        pass

    async def rerank_candidates(
        self,
        query_phrase: str,
        candidates: List[Any],
        context: Optional[Dict[str, Any]] = None
    ) -> List[Any]:
        """
        Rerank a small candidate list of products based on semantic similarity.
        Placeholder for Milestone 3.
        """
        return candidates
