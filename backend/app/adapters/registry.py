from typing import Dict, Type
from backend.app.adapters.base import BaseInputAdapter
from backend.app.adapters.plain_text import PlainTextAdapter

ADAPTER_REGISTRY: Dict[str, Type[BaseInputAdapter]] = {
    "plain_text": PlainTextAdapter,
    # Future: "pdf": PDFAdapter, "image": ImageAdapter, "email": EmailAdapter
}


def get_input_adapter(source_type: str) -> BaseInputAdapter:
    """Returns an instance of the adapter registered for source_type."""
    adapter_cls = ADAPTER_REGISTRY.get(source_type.lower())
    if not adapter_cls:
        raise ValueError(
            f"Unsupported input source type: '{source_type}'. "
            f"Supported types are: {list(ADAPTER_REGISTRY.keys())}"
        )
    return adapter_cls()
