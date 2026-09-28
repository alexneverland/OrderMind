import unicodedata
import re

GREEK_ACCENT_MAP = {
    'ά': 'α', 'έ': 'ε', 'ή': 'η', 'ί': 'ι', 'ό': 'ο', 'ύ': 'υ', 'ώ': 'ω',
    'ϊ': 'ι', 'ϋ': 'υ', 'ΐ': 'ι', 'ΰ': 'υ',
    'Ά': 'α', 'Έ': 'ε', 'Ή': 'η', 'Ί': 'ι', 'Ό': 'ο', 'Ύ': 'υ', 'Ώ': 'ω',
    'Ϊ': 'ι', 'Ϋ': 'υ',
    'ς': 'σ'
}

def normalize_text(text: str | None) -> str:
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
