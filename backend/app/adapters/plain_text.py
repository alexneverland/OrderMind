import hashlib
from typing import Any, Optional, Dict
from backend.app.adapters.base import BaseInputAdapter
from backend.app.schemas.adapters import NormalizedInput
from backend.app.core.text_normalizer import normalize_text


class PlainTextAdapter(BaseInputAdapter):
    """
    Adapter for processing raw plain text order inputs.
    """

    def normalize(self, raw_input: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedInput:
        if raw_input is None:
            raw_input = ""
        
        raw_text = str(raw_input)
        meta = metadata or {}

        # Compute deterministic SHA-256 hash for deduplication
        source_hash = hashlib.sha256(raw_text.strip().encode("utf-8")).hexdigest()

        # Generate normalized text: normalize each line while preserving newline linebreaks
        normalized_lines = [normalize_text(line) for line in raw_text.splitlines()]
        normalized_text = "\n".join(line for line in normalized_lines if line)

        return NormalizedInput(
            source_type="plain_text",
            raw_text=raw_text,
            normalized_text=normalized_text,
            sender_email=meta.get("sender_email"),
            sender_phone=meta.get("sender_phone"),
            original_filename=meta.get("original_filename"),
            mime_type="text/plain",
            source_hash=source_hash,
            metadata=meta
        )
