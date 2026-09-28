import pytest
from backend.app.core.text_normalizer import normalize_unit, is_noise_line, normalize_text


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


def test_unit_normalization_unknown_default():
    """Verify unknown or None units default to 'piece'."""
    assert normalize_unit(None) == "piece"
    assert normalize_unit("") == "piece"
    assert normalize_unit("unknown_unit") == "piece"


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
