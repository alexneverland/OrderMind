import json

import pytest
from google import genai

from backend.app.ai.remote_providers import OpenAIProvider, AnthropicProvider, VertexProvider
from backend.app.schemas.adapters import NormalizedInput


ORDER_JSON = json.dumps({"items": [{
    "original_text": "3 boxes olives", "product_phrase": "olives", "quantity": 3, "unit": "boxes",
}]})


@pytest.mark.asyncio
async def test_openai_uses_selected_model_for_text_extraction_and_photo_ocr(monkeypatch):
    calls = []

    class FakeResponses:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return type("Response", (), {"output_text": ORDER_JSON if len(calls) == 1 else "3 [UNCLEAR] olives"})()

    class FakeClient:
        responses = FakeResponses()

        async def close(self):
            pass

    monkeypatch.setattr(OpenAIProvider, "_client", lambda self: FakeClient())
    provider = OpenAIProvider()
    provider.model_name = "test-openai-model"
    items = await provider.extract_order(NormalizedInput(raw_text="3 boxes olives", normalized_text=""))
    assert items[0].original_text == "3 boxes olives"
    assert calls[0]["model"] == "test-openai-model"
    assert calls[0]["store"] is False
    assert await provider.transcribe_file(b"\xff\xd8\xff", "image/jpeg", "Read handwriting") == "3 [UNCLEAR] olives"
    assert calls[1]["input"][0]["content"][1]["type"] == "input_image"


@pytest.mark.asyncio
async def test_anthropic_uses_selected_model_for_text_extraction_and_pdf_ocr(monkeypatch):
    calls = []

    class FakeMessages:
        async def create(self, **kwargs):
            calls.append(kwargs)
            raw = ORDER_JSON if len(calls) == 1 else "3 [UNCLEAR] olives"
            return type("Response", (), {"content": [type("Block", (), {"type": "text", "text": raw})()]})()

    class FakeClient:
        messages = FakeMessages()

        async def close(self):
            pass

    monkeypatch.setattr(AnthropicProvider, "_client", lambda self: FakeClient())
    provider = AnthropicProvider()
    provider.model_name = "test-claude-model"
    items = await provider.extract_order(NormalizedInput(raw_text="3 boxes olives", normalized_text=""))
    assert items[0].original_text == "3 boxes olives"
    assert calls[0]["model"] == "test-claude-model"
    assert await provider.transcribe_file(b"%PDF", "application/pdf", "Read handwriting") == "3 [UNCLEAR] olives"
    assert calls[1]["messages"][0]["content"][1]["type"] == "document"


def test_vertex_uses_google_cloud_project_and_location(monkeypatch):
    captured = {}
    monkeypatch.setattr("backend.app.ai.remote_providers.settings.GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setattr("backend.app.ai.remote_providers.settings.GOOGLE_CLOUD_LOCATION", "europe-west1")

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(genai, "Client", fake_client)
    assert VertexProvider()._get_client() is not None
    assert captured == {"vertexai": True, "project": "test-project", "location": "europe-west1"}
