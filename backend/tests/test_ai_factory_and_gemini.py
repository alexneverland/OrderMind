import json
import pytest
from unittest.mock import MagicMock, patch

from backend.app.ai.factory import get_ai_provider
from backend.app.ai.mock_provider import MockAIProvider
from backend.app.ai.gemini_provider import GeminiProvider
from backend.app.schemas.adapters import NormalizedInput


def test_ai_provider_factory():
    """Verify factory returns appropriate provider and raises on unknown."""
    provider = get_ai_provider("mock")
    assert isinstance(provider, MockAIProvider)

    # Unknown provider
    with pytest.raises(ValueError, match="Unsupported AI provider"):
        get_ai_provider("non_existent_provider")


def test_gemini_provider_missing_key():
    """Verify GeminiProvider raises when API key is missing."""
    provider = GeminiProvider(api_key="")
    with pytest.raises(ValueError, match="GEMINI_API_KEY is not configured"):
        provider._get_client()


@pytest.mark.asyncio
async def test_gemini_provider_mocked_success():
    """Verify GeminiProvider successfully parses structured output from Gemini model."""
    provider = GeminiProvider(api_key="fake-test-key")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "items": [
            {
                "original_text": "3 κούτες ζαμπόν 500",
                "product_phrase": "ζαμπόν 500",
                "quantity": 3.0,
                "unit": "case"
            },
            {
                "original_text": "5 τεμ μπέικον",
                "product_phrase": "μπέικον",
                "quantity": 5.0,
                "unit": "piece"
            }
        ]
    })
    mock_client.models.generate_content.return_value = mock_response
    provider._client = mock_client

    inp = NormalizedInput(raw_text="3 κούτες ζαμπόν 500 και 5 τεμ μπέικον", normalized_text="")
    items = await provider.extract_order(inp)

    assert len(items) == 2
    assert items[0].product_phrase == "ζαμπόν 500"
    assert items[0].quantity == 3.0
    assert items[0].unit == "case"

    assert items[1].product_phrase == "μπέικον"
    assert items[1].quantity == 5.0
    assert items[1].unit == "piece"


@pytest.mark.asyncio
async def test_gemini_provider_malformed_response_handling():
    """Verify GeminiProvider retries and raises controlled error if model returns invalid JSON."""
    provider = GeminiProvider(api_key="fake-test-key")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "NOT_A_VALID_JSON_RESPONSE"
    mock_client.models.generate_content.return_value = mock_response
    provider._client = mock_client

    inp = NormalizedInput(raw_text="some order text", normalized_text="")
    with pytest.raises(ValueError, match="Gemini order extraction failed after 2 attempts"):
        await provider.extract_order(inp)

    # Verify it attempted 2 times
    assert mock_client.models.generate_content.call_count == 2
