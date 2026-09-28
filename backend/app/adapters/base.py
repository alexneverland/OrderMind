from abc import ABC, abstractmethod
from typing import Any, Optional, Dict
from backend.app.schemas.adapters import NormalizedInput


class BaseInputAdapter(ABC):
    """
    Abstract interface for channel input adapters.
    Converts diverse inputs (plain text, PDF, images, emails, etc.) into a canonical NormalizedInput.
    """

    @abstractmethod
    def normalize(self, raw_input: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedInput:
        """
        Normalize input into a canonical NormalizedInput structure.
        Must preserve the original input intact in raw_text.
        """
        pass
