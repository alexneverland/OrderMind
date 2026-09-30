import json
import logging
import asyncio
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.app.ai.prompt_boundaries import UNTRUSTED_CONTENT_POLICY, extraction_policy, untrusted_text_payload

from backend.app.ai.base import BaseAIProvider
from backend.app.config import settings
from backend.app.schemas.adapters import NormalizedInput
from backend.app.schemas.order import NormalizedOrderLineDraft
from backend.app.core.text_normalizer import resolve_unit

logger = logging.getLogger(__name__)


class GeminiExtractedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original_text: str = Field(description="Verbatim line or phrase from the raw input")
    product_phrase: str = Field(description="Requested product description without quantities or units")
    quantity: float = Field(ge=0, allow_inf_nan=False, description="Requested quantity, must be positive number")
    unit: Optional[str] = Field(default=None, description="Verbatim packaging or measurement unit if mentioned, or null if none mentioned")
    quantity_text: str = Field(description="Exact quantity expression, including its unit, as written by customer")
    bonus_quantity: float = Field(default=0, ge=0, allow_inf_nan=False, description="Free quantity; a bare free number shares the explicit unit of its paid quantity")

    @field_validator("quantity")
    @classmethod
    def positive_quantity(cls, value: float) -> float:
        # Gemini's response Schema does not support exclusiveMinimum. Keep the
        # strict positive check server-side rather than breaking SDK conversion.
        if value <= 0:
            raise ValueError("Requested quantity must be positive")
        return value


class GeminiExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: List[GeminiExtractedItem] = Field(default_factory=list)


EXTRACTION_SYSTEM_PROMPT = """You are a precise, deterministic B2B order extraction assistant.
Your ONLY task is to extract requested line items, quantities, and packaging units from the customer's text.

ABSOLUTE BOUNDARIES AND CONSTRAINTS:
1. Extraction ONLY: Do NOT guess SKUs, product codes, barcodes, or prices. If the customer supplied a product code, use that exact code as product_phrase; otherwise use the customer's product description.
2. Source of Truth: Do NOT invent products or match them against external catalogs.
3. No conversions: Do NOT convert cases into pieces or pallets into cartons. Extract the verbatim unit requested.
4. Filter noise: Ignore greetings, pleasantries, delivery instructions, or sign-offs (e.g. 'Καλημέρα', 'παρακαλώ', 'ευχαριστώ', 'στείλτε τα αύριο').
5. Units: Extract the verbatim unit as written by customer if mentioned (e.g. 'κούτες', 'κιλά', 'τεμάχια', 'trays', 'κιβώτια'). If NO unit is mentioned, return null for unit. Never invent or assume a unit.
6. Grounding: The original_text must be the exact verbatim snippet from the customer input.
7. Read each layout semantically: columns may vary, unrelated columns or headings may intervene, and one physical row can contain multiple products. Return one item per requested product. Include an exact quantity_text substring for each item. Preserve an explicitly requested free quantity separately. A bare free number shares the explicit unit of its paid quantity. Never infer bonus meaning from a plus sign unless the supplied company policy enables it. If two quantities explicitly use different units, preserve both unit tokens in quantity_text.
8. A product description or an M.M column can mention kilos or other units; that is product metadata. Set the order unit only from the quantity expression. If no order unit is explicitly stated, return null for unit; company policy will resolve it later. If the quantity explicitly says kilos or cases, return that unit exactly.
""" + "\n" + UNTRUSTED_CONTENT_POLICY


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

        bonus_mode = (context or {}).get("bonus_expression_mode", "disabled")
        policy = extraction_policy(bonus_mode)
        user_content = untrusted_text_payload(normalized_input.raw_text)

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                # Fully async call using client.aio to prevent blocking the event loop
                response = await client.aio.models.generate_content(
                    model=self.model_name,
                    contents=user_content,
                    config=types.GenerateContentConfig(
                        system_instruction=EXTRACTION_SYSTEM_PROMPT + "\n" + policy,
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
                        unit_explicit=unit_explicit,
                        quantity_text=item.quantity_text,
                        bonus_quantity=item.bonus_quantity,
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
