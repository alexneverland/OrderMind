import hashlib
import pytest

from backend.app.adapters.plain_text import PlainTextAdapter
from backend.app.adapters.registry import get_input_adapter, ADAPTER_REGISTRY
from backend.app.schemas.adapters import NormalizedInput


def test_plain_text_adapter_preserves_raw_text():
    """Verify that PlainTextAdapter never alters or strips the original raw text."""
    adapter = PlainTextAdapter()
    raw_sample = "   Καλημέρα!\n3 κούτες ζαμπόν 500\n  \nευχαριστώ.   "
    metadata = {"sender_email": "client@example.test", "sender_phone": "+306912345678"}

    normalized = adapter.normalize(raw_sample, metadata=metadata)

    assert isinstance(normalized, NormalizedInput)
    # The raw_text must be 100% identical to the input
    assert normalized.raw_text == raw_sample
    assert normalized.sender_email == "client@example.test"
    assert normalized.sender_phone == "+306912345678"
    assert normalized.source_type == "plain_text"
    assert normalized.mime_type == "text/plain"

    # Verify SHA-256 hash
    expected_hash = hashlib.sha256(raw_sample.strip().encode("utf-8")).hexdigest()
    assert normalized.source_hash == expected_hash

    # Normalized text has stripped accents & normalized case
    assert "3 κουτεσ ζαμπον 500" in normalized.normalized_text


def test_get_input_adapter_factory():
    """Verify adapter factory behavior and error handling for unknown adapters."""
    adapter = get_input_adapter("plain_text")
    assert isinstance(adapter, PlainTextAdapter)

    # Case-insensitive
    adapter_upper = get_input_adapter("PLAIN_TEXT")
    assert isinstance(adapter_upper, PlainTextAdapter)

    # Unsupported adapter
    with pytest.raises(ValueError, match="Unsupported input source type"):
        get_input_adapter("unsupported_format")
