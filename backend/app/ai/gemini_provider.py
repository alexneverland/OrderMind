import json
import logging
import asyncio
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from backend.app.ai.base import BaseAIProvider
from backend.app.config import settings
from backend.app.schemas.adapters import NormalizedInput
from backend.app.schemas.order import NormalizedOrderLineDraft
from backend.app.core.text_normalizer import resolve_unit

logger = logging.getLogger(__name__)


class GeminiExtractedItem(BaseModel):
    original_text: str = Field(description="Verbatim line or phrase from the raw input")
    product_phrase: str = Field(description="Requested product description without quantities or units")
    quantity: float = Field(description="Requested quantity, must be positive number")
    unit: Optional[str] = Field(default=None, description="Verbatim packaging or measurement unit if mentioned, or null if none mentioned")


class GeminiExtractionResponse(BaseModel):
    items: List[GeminiExtractedItem] = Field(default_factory=list)


EXTRACTION_SYSTEM_PROMPT = """You are a precise, deterministic B2B order extraction assistant.
Your ONLY task is to extract requested line items, quantities, and packaging units from the customer's text.

ABSOLUTE BOUNDARIES AND CONSTRAINTS:
1. Extraction ONLY: Do NOT guess SKUs, product codes, barcodes, or prices.
2. Source of Truth: Do NOT invent products or match them against external catalogs.
3. No conversions: Do NOT convert cases into pieces or pallets into cartons. Extract the verbatim unit requested.
4. Filter noise: Ignore greetings, pleasantries, delivery instructions, or sign-offs (e.g. 'Καλημέρα', 'παρακαλώ', 'ευχαριστώ', 'στείλτε τα αύριο').
5. Units: Extract the verbatim unit as written by customer if mentioned (e.g. 'κούτες', 'κιλά', 'τεμάχια', 'trays', 'κιβώτια'). If NO unit is mentioned, return null for unit. Never invent or assume a unit.
6. Grounding: The original_text must be the exact verbatim snippet from the customer input.
"""


class GeminiProvider(BaseAIProvider):
    """
    Production AI provider using official Google GenAI SDK (google-genai).
    Enforces fully async execution via client.aio, retries, and structured output.
    """
    name: str = "gemini"

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.AI_MODEL
        if self.model_name == "mock-model":
            self.model_name = "gemini-3.8-flash"
        self._client = None

    def _get_client(self):
        if not self.api_key:
            raise RuntimeError("AI extraction provider is unavailable")
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def extract_order(
        self,
        normalized_input: NormalizedInput,
        context: Optional[Dict[str, Any]] = None
    ) -> List[NormalizedOrderLineDraft]:
        client = self._get_client()
        from google.genai import types

        user_content = f"Extract items from this customer order:\n\"\"\"\n{normalized_input.raw_text}\n\"\"\""

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                # Fully async call using client.aio to prevent blocking the event loop
                response = await client.aio.models.generate_content(
                    model=self.model_name,
                    contents=user_content,
                    config=types.GenerateContentConfig(
                        system_instruction=EXTRACTION_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=GeminiExtractionResponse,
                        temperature=0.0,
                    ),
                )

                if not response.text:
                    raise ValueError("Gemini returned an empty response")

                # Parse & validate structured output
                data = json.loads(response.text)
                structured = GeminiExtractionResponse.model_validate(data)

                results: List[NormalizedOrderLineDraft] = []
                for item in structured.items:
                    if item.quantity <= 0:
                        continue
                    canonical_unit, raw_unit, unit_explicit = resolve_unit(item.unit)
                    results.append(NormalizedOrderLineDraft(
                        original_text=item.original_text,
                        product_phrase=item.product_phrase,
                        quantity=item.quantity,
                        unit=canonical_unit,
                        raw_unit=raw_unit,
                        unit_explicit=unit_explicit
                    ))

                return results

            except Exception as e:
                last_error = e
                logger.warning(
                    "Gemini async extraction attempt %d failed: %s",
                    attempt + 1,
                    type(e).__name__
                )
                # Retry brief upstream overloads, not malformed output or invalid credentials.
                if attempt + 1 >= max_retries or getattr(e, "code", None) not in {429, 500, 502, 503, 504}:
                    break
                await asyncio.sleep(2 ** attempt)

        raise RuntimeError("AI extraction provider is unavailable") from last_error
