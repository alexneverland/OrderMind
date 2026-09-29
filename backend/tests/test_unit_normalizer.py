import pytest
from backend.app.core.text_normalizer import (
    normalize_unit,
    resolve_unit,
    is_noise_line,
    is_grounded_in_input,
    normalize_text
)


def test_resolve_unit_unknown_explicit_does_not_become_piece():
    """
    CRITICAL: An unknown explicit unit (e.g. 'trays', 'ταψιά', 'κουβάδες')
    must NEVER silently become 'piece'.
    It must be preserved as unit='unknown', raw_unit='trays', unit_explicit=True.
    """
    canonical, raw, explicit = resolve_unit("trays")
    assert canonical == "unknown"
    assert raw == "trays"
    assert explicit is True

    canonical_gr, raw_gr, explicit_gr = resolve_unit("ταψιά")
    assert canonical_gr == "unknown"
    assert raw_gr == "ταψιά"
    assert explicit_gr is True

    canonical_box, raw_box, explicit_box = resolve_unit("κουβάδες")
    assert canonical_box == "unknown"
    assert raw_box == "κουβάδες"
    assert explicit_box is True


def test_resolve_unit_unspecified_behavior():
    """
    When no unit is mentioned (None or empty string):
    canonical='unknown', raw_unit=None, unit_explicit=False.
    """
    canonical, raw, explicit = resolve_unit(None)
    assert canonical == "unknown"
    assert raw is None
    assert explicit is False

    canonical_empty, raw_empty, explicit_empty = resolve_unit("   ")
    assert canonical_empty == "unknown"
    assert raw_empty is None
    assert explicit_empty is False


def test_resolve_unit_known_explicit():
    """Known explicit units must have unit_explicit=True and preserve raw_unit."""
    canonical, raw, explicit = resolve_unit("κούτες")
    assert canonical == "case"
    assert raw == "κούτες"
    assert explicit is True

    canonical_kg, raw_kg, explicit_kg = resolve_unit("κιλά")
    assert canonical_kg == "kg"
    assert raw_kg == "κιλά"
    assert explicit_kg is True


def test_unit_normalization_piece_variations():
    """Verify piece variations normalize to 'piece'."""
    assert normalize_unit("τεμάχιο") == "piece"
    assert normalize_unit("τεμάχια") == "piece"
    assert normalize_unit("τεμ") == "piece"
    assert normalize_unit("τεμ.") == "piece"
    assert normalize_unit("pcs") == "piece"
    assert normalize_unit("piece") == "piece"
    assert normalize_unit("pieces") == "piece"
    assert normalize_unit("τεμχ") == "piece"


def test_unit_normalization_case_variations():
    """Verify case/box variations normalize to 'case'."""
    assert normalize_unit("κούτα") == "case"
    assert normalize_unit("κούτες") == "case"
    assert normalize_unit("κιβώτιο") == "case"
    assert normalize_unit("κιβώτια") == "case"
    assert normalize_unit("κιβ") == "case"
    assert normalize_unit("κιβ.") == "case"
    assert normalize_unit("case") == "case"
    assert normalize_unit("carton") == "case"
    assert normalize_unit("box") == "case"
    assert normalize_unit("boxes") == "case"


def test_unit_normalization_kg_and_pallet():
    """Verify kg and pallet variations."""
    assert normalize_unit("κιλό") == "kg"
    assert normalize_unit("κιλά") == "kg"
    assert normalize_unit("kg") == "kg"
    assert normalize_unit("kgs") == "kg"
    assert normalize_unit("kgr") == "kg"

    assert normalize_unit("παλέτα") == "pallet"
    assert normalize_unit("παλέτες") == "pallet"
    assert normalize_unit("pallet") == "pallet"


def test_noise_line_detection():
    """Verify pleasantries and greetings without order items are recognized as noise."""
    assert is_noise_line("Καλημέρα") is True
    assert is_noise_line("Καλησπέρα σας,") is True
    assert is_noise_line("ευχαριστώ πολύ!") is True
    assert is_noise_line("Καλή συνέχεια") is True
    assert is_noise_line("") is True

    # Real order lines with quantities must NOT be classified as noise
    assert is_noise_line("3 κούτες ζαμπόν 500") is False
    assert is_noise_line("5 τεμ μπέικον") is False
    assert is_noise_line("10 κόκκινα") is False


def test_is_grounded_in_input():
    """Verify input grounding check correctly accepts real input fragments and rejects fabrications."""
    raw_input = "Καλημέρα,\nθέλω 4 κούτες ζαμπόν 500\nκαι 10 τεμάχια μπέικον\nευχαριστώ!"

    # Grounded fragments (punctuation/whitespace differences handled safely)
    assert is_grounded_in_input("4 κούτες ζαμπόν 500", raw_input) is True
    assert is_grounded_in_input("ζαμπόν 500", raw_input) is True
    assert is_grounded_in_input("10 τεμάχια μπέικον", raw_input) is True
    assert is_grounded_in_input("μπέικον", raw_input) is True

    # Fabricated / hallucinated items must FAIL grounding
    assert is_grounded_in_input("10 γάλατα φρέσκα", raw_input) is False
    assert is_grounded_in_input("τυρί φέτα 2kg", raw_input) is False
