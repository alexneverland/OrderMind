import unicodedata
import re
from typing import Optional, Tuple, List

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
UNIT_MAPPING = {normalize_text(k): v for k, v in RAW_UNIT_MAPPING.items()}


def resolve_unit(unit_str: Optional[str]) -> Tuple[str, Optional[str], bool]:
    """
    Resolves unit string into:
    - canonical_unit: "piece" | "case" | "kg" | "pallet" | "unknown"
    - raw_unit: original verbatim unit text if mentioned
    - unit_explicit: True if a unit was explicitly mentioned in the order

    Critical safety guarantees:
    1. Unspecified unit -> ("piece", None, False)
    2. Known explicit unit -> (canonical, raw_unit, True)
    3. Unknown explicit unit (e.g. "trays") -> ("unknown", "trays", True) [NEVER silently turned to piece!]
    """
    if not unit_str or not str(unit_str).strip():
        return ("piece", None, False)

    raw_clean = str(unit_str).strip()
    norm_unit = normalize_text(raw_clean)

    if norm_unit in UNIT_MAPPING:
        return (UNIT_MAPPING[norm_unit], raw_clean, True)

    # Unit was explicitly provided but is unknown to our catalog mapping
    return ("unknown", raw_clean, True)


def normalize_unit(unit_str: Optional[str]) -> str:
    """Backwards-compatible helper returning canonical unit."""
    canonical, _, _ = resolve_unit(unit_str)
    return canonical


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
    
    for pattern in CLOSING_PATTERNS:
        if re.match(pattern, norm):
            return True
            
    for pattern in GREETING_PATTERNS:
        if re.match(pattern, norm) and not re.search(r"\d", norm):
            return True

    return False


def is_grounded_in_input(fragment: str, raw_input: str) -> bool:
    """
    Verifies that an extracted fragment is traceable to the customer's raw input.
    Uses normalized text and token presence so minor punctuation/whitespace differences
    do not break verification, while completely fabricated/hallucinated items are rejected.
    """
    if not fragment or not raw_input:
        return False
    norm_frag = normalize_text(fragment)
    norm_input = normalize_text(raw_input)
    if not norm_frag:
        return False
    
    # 1. Direct normalized substring check
    if norm_frag in norm_input:
        return True
    
    # 2. Token overlap check: all non-trivial tokens of fragment must be present in raw input
    frag_tokens = [t for t in norm_frag.split() if len(t) > 1]
    if not frag_tokens:
        return norm_frag in norm_input
        
    input_tokens = set(norm_input.split())
    matched_tokens = sum(1 for t in frag_tokens if t in input_tokens)
    return (matched_tokens / len(frag_tokens)) >= 0.8


def extract_numbers_from_text(text: str) -> List[float]:
    """Extracts numeric values from digit sequences and common number words."""
    if not text:
        return []
    norm = normalize_text(text)
    numbers = []

    matches = re.findall(r"\b\d+(?:[.,]\d+)?\b", text)
    for m in matches:
        try:
            numbers.append(float(m.replace(",", ".")))
        except ValueError:
            pass

    word_map = {
        "ενα": 1.0, "ενας": 1.0, "μια": 1.0, "δυο": 2.0, "τρια": 3.0, "τρεις": 3.0,
        "τεσσερα": 4.0, "τεσσερις": 4.0, "πεντε": 5.0, "εξι": 6.0, "επτα": 7.0,
        "οκτω": 8.0, "εννεα": 9.0, "δεκα": 10.0, "μισο": 0.5, "μισος": 0.5,
        "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0,
        "six": 6.0, "seven": 7.0, "eight": 8.0, "nine": 9.0, "ten": 10.0
    }
    for token in norm.split():
        if token in word_map:
            numbers.append(word_map[token])

    return numbers


def is_quantity_grounded_in_span(quantity: float, text_span: str, raw_input: str) -> bool:
    """
    Verifies that the extracted numerical quantity is grounded in the text span or input.
    - If the text span contains explicit digits/numbers: the extracted quantity must match one of them.
    - If no numbers are present in the text span: a quantity of 1.0 (default implicit quantity) is acceptable.
    - If provider hallucinated an arbitrary quantity (e.g. text has '2' but provider returns 20): returns False.
    """
    span_numbers = extract_numbers_from_text(text_span)
    if span_numbers:
        return any(abs(quantity - n) < 1e-4 for n in span_numbers)

    input_numbers = extract_numbers_from_text(raw_input)
    if any(abs(quantity - n) < 1e-4 for n in input_numbers):
        return True

    if not span_numbers and quantity == 1.0:
        return True

    return False


def is_unit_grounded_in_span(
    unit: str,
    raw_unit: Optional[str],
    unit_explicit: bool,
    text_span: str,
    raw_input: str
) -> bool:
    """
    Verifies that an extracted unit is grounded in the customer's text.
    - If unit_explicit is True:
      - raw_unit must appear in the text_span or raw_input.
      - If input specifies a conflicting unit (e.g. 'cases' while extracted is 'kg'), it is rejected.
    - If unit_explicit is False:
      - Valid default when customer didn't specify a unit.
    """
    if not unit_explicit:
        return True

    if not raw_unit or not raw_unit.strip():
        return False

    norm_raw_unit = normalize_text(raw_unit)
    norm_span = normalize_text(text_span)
    norm_input = normalize_text(raw_input)

    if norm_raw_unit in norm_span or norm_raw_unit in norm_input:
        return True

    unit_norm = normalize_text(unit)
    if unit_norm in norm_span or unit_norm in norm_input:
        return True

    return False


GREEK_STEM_ENDINGS = [
    normalize_text(e)
    for e in ['ια', 'ες', 'οι', 'ου', 'ων', 'ους', 'ας', 'ης', 'ος', 'α', 'ο', 'η', 'ι', 'ε', 'υ']
]


def greek_stem(word: str) -> str:
    """
    Lightweight Greek inflection stemmer for singular/plural order phrases.
    e.g. 'κοκκινο' -> 'κοκκιν', 'κοκκινα' -> 'κοκκιν'
    """
    word = normalize_text(word).strip()
    for ending in sorted(GREEK_STEM_ENDINGS, key=len, reverse=True):
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[:-len(ending)]
    return word


def stem_phrase(phrase: Optional[str]) -> str:
    """
    Computes stemmed phrase across all tokens for Greek order phrase matching.
    e.g. 'κοκκινο' -> 'κοκκιν', 'κοκκινα' -> 'κοκκιν'
         'γαλοπουλα καπνιστη' -> 'γαλοπουλ καπνιστ', 'γαλοπουλες καπνιστες' -> 'γαλοπουλ καπνιστ'
    """
    if not phrase:
        return ""
    norm = normalize_text(phrase)
    return " ".join(greek_stem(w) for w in norm.split())

