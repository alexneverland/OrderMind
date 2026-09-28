import re
from typing import List, Optional, Dict, Any
from backend.app.ai.base import BaseAIProvider
from backend.app.schemas.adapters import NormalizedInput
from backend.app.schemas.order import NormalizedOrderLineDraft
from backend.app.core.text_normalizer import resolve_unit, is_noise_line

RAW_UNITS = [
    "κουτες", "κούτες", "κουτα", "κούτα", "κιβωτια", "κιβώτια", "κιβωτιο", "κιβώτιο", "κιβ",
    "τεμαχια", "τεμάχια", "τεμαχιο", "τεμάχιο", "τεμχ", "τεμ", "τεμ.", "pcs", "pieces", "piece",
    "κιλα", "κιλά", "κιλο", "κιλό", "kg", "kgs", "kgr", "kilo", "kilos",
    "παλετες", "παλέτες", "παλετα", "παλέτα", "pallets", "pallet",
    "cartons", "carton", "boxes", "box",
    "trays", "tray", "ταψια", "ταψιά", "ταψι", "ταψί",
    "κουβαδες", "κουβάδες", "κουβας", "κουβάς",
    "βαζα", "βάζα", "βαζο", "βάζο",
    "δοχεια", "δοχεία", "δοχειο", "δοχείο",
    "σακουλες", "σακούλες", "σακουλα", "σακούλα",
    "πακετα", "πακέτα", "πακετο", "πακέτο"
]
# Sort by length descending so longer tokens take precedence over shorter prefixes (e.g. 'trays' before 'tray')
RAW_UNITS.sort(key=len, reverse=True)
UNIT_PATTERN = r"(?:" + "|".join(re.escape(u) for u in RAW_UNITS) + r")"

PREFIX_PATTERN = r"^\s*(?:και\s+)?(?:(?:βαλε|βάλε|στειλε|στείλε|γραψε|γράψε|θελω|θέλω|θελουμε|θέλουμε)\s+(?:μου\s+)?)?"

# Regex matching leading conversational prefix, quantity, optional unit, and product phrase
ITEM_PATTERN = re.compile(
    PREFIX_PATTERN +
    rf"(\d+(?:[.,]\d+)?)\s*"                          # Group 1: Quantity
    rf"({UNIT_PATTERN})?\s*"                           # Group 2: Unit (optional)
    rf"(?:απο\s+(?:τα\s+)?)?"                          # Optional "από τα"
    rf"(.+?)\s*$",                                     # Group 3: Product phrase
    re.IGNORECASE | re.UNICODE
)


class MockAIProvider(BaseAIProvider):
    """
    Deterministic rule-based AI Provider mock.
    Allows running test suites and offline local development without API keys or token costs.
    """
    name: str = "mock"

    async def extract_order(
        self,
        normalized_input: NormalizedInput,
        context: Optional[Dict[str, Any]] = None
    ) -> List[NormalizedOrderLineDraft]:
        raw_text = normalized_input.raw_text
        if not raw_text or not raw_text.strip():
            return []

        # Split input into lines
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        extracted_items: List[NormalizedOrderLineDraft] = []

        for line in lines:
            # Skip conversational pleasantries (e.g. "Καλημέρα", "ευχαριστώ")
            if is_noise_line(line):
                continue

            # Strip leading greeting if glued into the same line (e.g. "Καλημέρα θέλω 3 κούτες...")
            cleaned_line = re.sub(
                r"^(?:καλημερα|καλησπερα|γεια\s+σας|γεια|χαιρετε|γεια\s+σου)[\s,!.]*",
                "",
                line,
                flags=re.IGNORECASE
            ).strip()

            if not cleaned_line:
                continue

            # Check if line contains multiple clauses joined by " και " (e.g. "3 ζαμπόν και 4 μπέικον")
            # Only split on " και " if followed by a digit
            sub_segments = re.split(r"\s+και\s+(?=\d)", cleaned_line, flags=re.IGNORECASE)

            for segment in sub_segments:
                seg_stripped = segment.strip().rstrip(",;.")
                if not seg_stripped:
                    continue

                match = ITEM_PATTERN.match(seg_stripped)
                if match:
                    qty_str, unit_str, product_phrase = match.groups()
                    qty = float(qty_str.replace(",", "."))
                    canonical_unit, raw_unit, unit_explicit = resolve_unit(unit_str)
                    
                    # Clean trailing punctuation and unwanted colon from product phrase
                    cleaned_phrase = product_phrase.strip().rstrip(",;:.")
                    if cleaned_phrase:
                        extracted_items.append(NormalizedOrderLineDraft(
                            original_text=seg_stripped,
                            product_phrase=cleaned_phrase,
                            quantity=qty,
                            unit=canonical_unit,
                            raw_unit=raw_unit,
                            unit_explicit=unit_explicit
                        ))
                else:
                    # Fallback: check if line ends with a quantity (e.g. "ζαμπόν 500 3 κούτες")
                    reverse_match = re.search(rf"^(.+?)\s+(\d+(?:[.,]\d+)?)\s*({UNIT_PATTERN})?$", seg_stripped, re.IGNORECASE)
                    if reverse_match:
                        product_phrase, qty_str, unit_str = reverse_match.groups()
                        qty = float(qty_str.replace(",", "."))
                        canonical_unit, raw_unit, unit_explicit = resolve_unit(unit_str)
                        cleaned_phrase = product_phrase.strip().rstrip(",;:.")
                        if cleaned_phrase:
                            extracted_items.append(NormalizedOrderLineDraft(
                                original_text=seg_stripped,
                                product_phrase=cleaned_phrase,
                                quantity=qty,
                                unit=canonical_unit,
                                raw_unit=raw_unit,
                                unit_explicit=unit_explicit
                            ))

        return extracted_items
