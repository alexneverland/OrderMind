"""OpenAI and Anthropic extraction adapters for the existing grounded order flow."""

import base64
import json
from typing import Any, Dict, List, Optional

from backend.app.ai.base import BaseAIProvider
from backend.app.ai.gemini_provider import GeminiExtractionResponse, EXTRACTION_SYSTEM_PROMPT, GeminiProvider
from backend.app.config import settings
from backend.app.core.text_normalizer import resolve_unit
from backend.app.schemas.adapters import NormalizedInput
from backend.app.schemas.order import NormalizedOrderLineDraft


def _drafts(raw: str) -> List[NormalizedOrderLineDraft]:
    if not raw:
        raise ValueError("AI provider returned no order text")
    payload = json.loads(raw)
    structured = GeminiExtractionResponse.model_validate(payload)
    results = []
    for item in structured.items:
        if item.quantity <= 0:
            continue
        unit, raw_unit, unit_explicit = resolve_unit(item.unit)
        results.append(NormalizedOrderLineDraft(
            original_text=item.original_text,
            product_phrase=item.product_phrase,
            quantity=item.quantity,
            unit=unit,
            raw_unit=raw_unit,
            unit_explicit=unit_explicit,
            quantity_text=item.quantity_text,
            bonus_quantity=item.bonus_quantity,
        ))
    return results


class OpenAIProvider(BaseAIProvider):
    name = "openai"

    def __init__(self):
        self.model_name = settings.AI_MODEL

    def _client(self):
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OpenAI API key is not configured")
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60.0, max_retries=1)

    async def _complete(self, prompt: str, file: bytes | None = None, mime_type: str | None = None) -> str:
        client = self._client()
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        if file is not None and mime_type:
            data = base64.b64encode(file).decode("ascii")
            if mime_type == "application/pdf":
                content.append({"type": "input_file", "filename": "order.pdf", "file_data": f"data:{mime_type};base64,{data}"})
            else:
                content.append({"type": "input_image", "image_url": f"data:{mime_type};base64,{data}"})
        try:
            response = await client.responses.create(
                model=self.model_name,
                instructions=EXTRACTION_SYSTEM_PROMPT if file is None else None,
                input=[{"role": "user", "content": content}],
                max_output_tokens=16000,
                store=False,
            )
            return response.output_text or ""
        finally:
            await client.close()

    async def extract_order(self, normalized_input: NormalizedInput, context: Optional[Dict[str, Any]] = None) -> List[NormalizedOrderLineDraft]:
        try:
            return _drafts(await self._complete(
                "Return only JSON with an items array. Each item has original_text (exact substring), product_phrase, positive paid quantity, verbatim quantity_text, bonus_quantity (zero if none), and verbatim unit or null. Customer order:\n" + normalized_input.raw_text
            ))
        except Exception as exc:
            raise RuntimeError("OpenAI extraction provider is unavailable") from exc

    async def transcribe_file(self, content: bytes, mime_type: str, prompt: str) -> str:
        return await self._complete(prompt, content, mime_type)


class AnthropicProvider(BaseAIProvider):
    name = "anthropic"

    def __init__(self):
        self.model_name = settings.AI_MODEL

    def _client(self):
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("Anthropic API key is not configured")
        from anthropic import AsyncAnthropic
        return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=60.0, max_retries=1)

    async def _complete(self, prompt: str, file: bytes | None = None, mime_type: str | None = None) -> str:
        client = self._client()
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if file is not None and mime_type:
            source = {"type": "base64", "media_type": mime_type, "data": base64.b64encode(file).decode("ascii")}
            content.append({"type": "document" if mime_type == "application/pdf" else "image", "source": source})
        try:
            response = await client.messages.create(
                model=self.model_name,
                max_tokens=16000,
                system=EXTRACTION_SYSTEM_PROMPT if file is None else "Transcribe only what is visible; never infer missing text.",
                messages=[{"role": "user", "content": content}],
            )
            return "\n".join(block.text for block in response.content if block.type == "text")
        finally:
            await client.close()

    async def extract_order(self, normalized_input: NormalizedInput, context: Optional[Dict[str, Any]] = None) -> List[NormalizedOrderLineDraft]:
        try:
            return _drafts(await self._complete(
                "Return only JSON with an items array. Each item has original_text (exact substring), product_phrase, positive paid quantity, verbatim quantity_text, bonus_quantity (zero if none), and verbatim unit or null. Customer order:\n" + normalized_input.raw_text
            ))
        except Exception as exc:
            raise RuntimeError("Anthropic extraction provider is unavailable") from exc

    async def transcribe_file(self, content: bytes, mime_type: str, prompt: str) -> str:
        return await self._complete(prompt, content, mime_type)


class VertexProvider(GeminiProvider):
    name = "vertex"

    def __init__(self):
        super().__init__(api_key=None, model_name=settings.AI_MODEL)

    def _get_client(self):
        if not settings.GOOGLE_CLOUD_PROJECT:
            raise RuntimeError("Google Cloud project is not configured for Vertex")
        if self._client is None:
            from google import genai
            self._client = genai.Client(
                vertexai=True,
                project=settings.GOOGLE_CLOUD_PROJECT,
                location=settings.GOOGLE_CLOUD_LOCATION or "us-central1",
            )
        return self._client
