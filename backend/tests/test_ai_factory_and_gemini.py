import json
import pytest
from unittest.mock import MagicMock, AsyncMock

from backend.app.ai.factory import get_ai_provider, IMPLEMENTED_PROVIDERS, PLANNED_PROVIDERS
from backend.app.ai.mock_provider import MockAIProvider
from backend.app.ai.gemini_provider import GeminiProvider
from backend.app.schemas.adapters import NormalizedInput


def test_ai_provider_factory_distinction():
    """
    Verify factory enforces strict distinction between implemented and planned providers.
    """
    # Implemented provider
    provider = get_ai_provider("mock")
    assert isinstance(provider, MockAIProvider)

    # Planned stub providers must raise NotImplementedError
    for planned in PLANNED_PROVIDERS:
        with pytest.raises(NotImplementedError, match="is planned for a future release"):
            get_ai_provider(planned)

    # Completely unknown provider must raise ValueError
    with pytest.raises(ValueError, match="Unknown AI provider"):
        get_ai_provider("non_existent_provider_xyz")


def test_gemini_provider_missing_key():
    """Verify GeminiProvider raises when API key is missing."""
    provider = GeminiProvider(api_key="")
    with pytest.raises(RuntimeError, match="AI extraction provider is unavailable"):
        provider._get_client()


@pytest.mark.asyncio
async def test_gemini_provider_async_call_and_unit_resolution():
    """
    Verify GeminiProvider uses client.aio for non-blocking async execution,
    and properly resolves units (known, unknown container, and unspecified).
    """
    provider = GeminiProvider(api_key="fake-test-key")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "items": [
            {
                "original_text": "3 κούτες ζαμπόν 500",
                "product_phrase": "ζαμπόν 500",
                "quantity": 3.0,
                "unit": "κούτες"
            },
            {
                "original_text": "5 trays μπέικον",
                "product_phrase": "μπέικον",
                "quantity": 5.0,
                "unit": "trays"
            },
            {
                "original_text": "10 κόκκινα",
                "product_phrase": "κόκκινα",
                "quantity": 10.0,
                "unit": None
            }
        ]
    })
    
    # client.aio.models.generate_content must be an async coroutine
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    raw_text = "3 κούτες ζαμπόν 500 και 5 trays μπέικον και 10 κόκκινα"
    inp = NormalizedInput(raw_text=raw_text, normalized_text="")
    items = await provider.extract_order(inp)

    # Verify that client.aio was called and awaited
    assert mock_client.aio.models.generate_content.await_count == 1
    assert len(items) == 3

    # Item 1: Known explicit unit
    assert items[0].product_phrase == "ζαμπόν 500"
    assert items[0].quantity == 3.0
    assert items[0].unit == "case"
    assert items[0].raw_unit == "κούτες"
    assert items[0].unit_explicit is True

    # Item 2: Unknown explicit unit (MUST NOT become piece!)
    assert items[1].product_phrase == "μπέικον"
    assert items[1].quantity == 5.0
    assert items[1].unit == "unknown"
    assert items[1].raw_unit == "trays"
    assert items[1].unit_explicit is True

    # Item 3: Unspecified unit
    assert items[2].product_phrase == "κόκκινα"
    assert items[2].quantity == 10.0
    assert items[2].unit == "piece"
    assert items[2].raw_unit is None
    assert items[2].unit_explicit is False


@pytest.mark.asyncio
async def test_gemini_provider_malformed_response_handling():
    """Verify GeminiProvider retries and raises controlled error if model returns invalid JSON."""
    provider = GeminiProvider(api_key="fake-test-key")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "NOT_A_VALID_JSON_RESPONSE"
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    inp = NormalizedInput(raw_text="some order text", normalized_text="")
    with pytest.raises(RuntimeError, match="AI extraction provider is unavailable"):
        await provider.extract_order(inp)

    # Verify it attempted 2 async calls
    assert mock_client.aio.models.generate_content.await_count == 2
