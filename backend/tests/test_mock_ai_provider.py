import pytest
from backend.app.ai.mock_provider import MockAIProvider
from backend.app.schemas.adapters import NormalizedInput


@pytest.mark.asyncio
async def test_mock_ai_provider_single_line_variations():
    """Test standard single line items with different units and numbers."""
    provider = MockAIProvider()

    # 1. "3 κούτες ζαμπόν 500"
    inp1 = NormalizedInput(raw_text="3 κούτες ζαμπόν 500", normalized_text="3 κουτεσ ζαμπον 500")
    items1 = await provider.extract_order(inp1)
    assert len(items1) == 1
    assert items1[0].quantity == 3.0
    assert items1[0].unit == "case"
    assert items1[0].product_phrase == "ζαμπόν 500"

    # 2. "5 τεμάχια μπέικον"
    inp2 = NormalizedInput(raw_text="5 τεμάχια μπέικον", normalized_text="")
    items2 = await provider.extract_order(inp2)
    assert len(items2) == 1
    assert items2[0].quantity == 5.0
    assert items2[0].unit == "piece"
    assert items2[0].product_phrase == "μπέικον"

    # 3. "5 τεμ μπέικον"
    inp3 = NormalizedInput(raw_text="5 τεμ μπέικον", normalized_text="")
    items3 = await provider.extract_order(inp3)
    assert len(items3) == 1
    assert items3[0].quantity == 5.0
    assert items3[0].unit == "piece"
    assert items3[0].product_phrase == "μπέικον"

    # 4. "2 κιλά σαλάμι"
    inp4 = NormalizedInput(raw_text="2 κιλά σαλάμι", normalized_text="")
    items4 = await provider.extract_order(inp4)
    assert len(items4) == 1
    assert items4[0].quantity == 2.0
    assert items4[0].unit == "kg"
    assert items4[0].product_phrase == "σαλάμι"

    # 5. "10 κοκκινα" (no explicit unit, defaults to piece)
    inp5 = NormalizedInput(raw_text="10 κοκκινα", normalized_text="")
    items5 = await provider.extract_order(inp5)
    assert len(items5) == 1
    assert items5[0].quantity == 10.0
    assert items5[0].unit == "piece"
    assert items5[0].product_phrase == "κοκκινα"


@pytest.mark.asyncio
async def test_mock_ai_provider_connector_and_multiline():
    """Test order with 'και' and multiline email style with greeting/closing."""
    provider = MockAIProvider()

    # "βάλε μου 3 ζαμπόν και 4 μπέικον"
    inp1 = NormalizedInput(raw_text="βάλε μου 3 ζαμπόν και 4 μπέικον", normalized_text="")
    items1 = await provider.extract_order(inp1)
    assert len(items1) == 2
    assert items1[0].quantity == 3.0
    assert items1[0].product_phrase == "ζαμπόν"
    assert items1[1].quantity == 4.0
    assert items1[1].product_phrase == "μπέικον"

    # Multiline with greetings
    raw_text = """
    Καλημέρα,
    θέλω:
    3 κούτες ζαμπόν
    5 μπέικον
    ευχαριστώ
    """
    inp2 = NormalizedInput(raw_text=raw_text, normalized_text="")
    items2 = await provider.extract_order(inp2)
    assert len(items2) == 2
    assert items2[0].quantity == 3.0
    assert items2[0].unit == "case"
    assert items2[0].product_phrase == "ζαμπόν"

    assert items2[1].quantity == 5.0
    assert items2[1].unit == "piece"
    assert items2[1].product_phrase == "μπέικον"


@pytest.mark.asyncio
async def test_mock_ai_provider_messy_input():
    """Test irregular whitespace and punctuation."""
    provider = MockAIProvider()
    raw = "   \n\n  10   κουτες   Γαλοπούλα Καπνιστή 1kg,,  \n   2,5 κιλά   Φέτα ΠΟΠ.  \n"
    inp = NormalizedInput(raw_text=raw, normalized_text="")
    items = await provider.extract_order(inp)
    assert len(items) == 2
    assert items[0].quantity == 10.0
    assert items[0].unit == "case"
    assert items[0].product_phrase == "Γαλοπούλα Καπνιστή 1kg"

    assert items[1].quantity == 2.5
    assert items[1].unit == "kg"
    assert items[1].product_phrase == "Φέτα ΠΟΠ"
