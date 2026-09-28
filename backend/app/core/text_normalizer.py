import unicodedata
import re
from typing import Optional, List

GREEK_ACCENT_MAP = {
    'ά': 'α', 'έ': 'ε', 'ή': 'η', 'ί': 'ι', 'ό': 'ο', 'ύ': 'υ', 'ώ': 'ω',
    'ϊ': 'ι', 'ϋ': 'υ', 'ΐ': 'ι', 'ΰ': 'υ',
    'Ά': 'α', 'Έ': 'ε', 'Ή': 'η', 'Ί': 'ι', 'Ό': 'ο', 'Ύ': 'υ', 'Ώ': 'ω',
    'Ϊ': 'ι', 'Ϋ': 'υ',
    'ς': 'σ'
}

RAW_UNIT_MAPPING = {
    # Piece
    "τεμαχιο": "piece",
    "τεμαχια": "piece",
    "τεμ": "piece",
    "τεμ.": "piece",
    "τεμχ": "piece",
    "pcs": "piece",
    "pc": "piece",
    "piece": "piece",
    "pieces": "piece",
    "κομματι": "piece",
    "κομματια": "piece",

    # Case / Box
    "κουτα": "case",
    "κουτες": "case",
    "κιβωτιο": "case",
    "κιβωτια": "case",
    "κιβ": "case",
    "κιβ.": "case",
    "case": "case",
    "cases": "case",
    "carton": "case",
    "cartons": "case",
    "box": "case",
    "boxes": "case",
    "χαρτοκιβωτιο": "case",
    "χαρτοκιβωτια": "case",

    # Kilogram
    "κιλο": "kg",
    "κιλα": "kg",
    "kg": "kg",
    "kgs": "kg",
    "kgr": "kg",
    "kilo": "kg",
    "kilos": "kg",

    # Pallet
    "παλετα": "pallet",
    "παλετες": "pallet",
    "pallet": "pallet",
    "pallets": "pallet",
    "παλετ": "pallet",
}


def normalize_text(text: Optional[str]) -> str:
    """
    Normalizes Greek and Latin text:
    - Strips accents/diacritics
    - Converts to lowercase
    - Converts final sigma 'ς' to 'σ'
    - Removes excessive whitespaces and punctuation
    """
    if not text:
        return ""
    
    text = str(text).strip().lower()
    
    # Replace Greek accented vowels and final sigma
    normalized_chars = [GREEK_ACCENT_MAP.get(ch, ch) for ch in text]
    text = "".join(normalized_chars)
    
    # Also apply general unicode decomposition for other languages
    decomposed = unicodedata.normalize('NFD', text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != 'Mn')
    
    # Clean non-alphanumeric except spaces
    cleaned = re.sub(r'[^\w\s]', ' ', stripped, flags=re.UNICODE)
    # Collapse multiple whitespaces
    collapsed = re.sub(r'\s+', ' ', cleaned).strip()
    return collapsed


# Pre-computed map where all keys are normalized with normalize_text
# This ensures that keys with 'ς' and accented vowels match seamlessly!
UNIT_MAPPING = {normalize_text(k): v for k, v in RAW_UNIT_MAPPING.items()}


def normalize_unit(unit_str: Optional[str]) -> str:
    """
    Normalizes Greek and Latin quantity units to standard canonical values:
    - "piece", "case", "kg", "pallet".
    Defaults to "piece" if unknown or unspecified.
    """
    if not unit_str:
        return "piece"
    
    clean_unit = normalize_text(unit_str)
    return UNIT_MAPPING.get(clean_unit, "piece")


CLOSING_PATTERNS = [
    r"^(?:ευχαριστω|ευχαριστουμε)(?:\s+πολυ)?[\s,!.]*$",
    r"^(?:καλη\s+συνεχεια|χαιρετισμους|φιλικα|με\s+εκτιμηση)[\s,!.]*$",
]

GREETING_PATTERNS = [
    r"^(?:καλημερα|καλησπερα|γεια\s+σας|γεια|χαιρετε|γεια\s+σου)[\s,!.]*",
    r"^(?:θελω|θελουμε|βαλε\s+μου|βαλε|στειλε\s+μου|στειλε|γραψε\s+μου|παραγγελια)[\s,!.:-]*$",
]


def is_noise_line(line: str) -> bool:
    """Detects conversational pleasantries that contain no order items."""
    norm = normalize_text(line)
    if not norm:
        return True
    
    # Check exact closing match
    for pattern in CLOSING_PATTERNS:
        if re.match(pattern, norm):
            return True
            
    # Check if line is purely a greeting without any digits or item indicators
    for pattern in GREETING_PATTERNS:
        if re.match(pattern, norm) and not re.search(r"\d", norm):
            return True

    return False
