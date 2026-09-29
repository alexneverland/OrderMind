"""Resolve a requested unit to one concrete product packaging."""

from typing import Optional, Tuple

from backend.app.core.text_normalizer import normalize_text, normalize_unit
from backend.app.models.product import Product


def packaging_unit(package_type: str) -> str:
    """Recognize both canonical types and labels such as 'Κιβώτιο 10τεμ'."""
    normalized = normalize_text(package_type)
    return normalize_unit(normalized.split()[0]) if normalized else "unknown"


def _matches_unit(product: Product, pkg, unit: str) -> bool:
    return packaging_unit(pkg.package_type) == unit or (
        unit != normalize_unit(product.unit) and normalize_unit(pkg.unit) == unit
    )


def resolve_product_packaging(
    product: Product, requested_unit: str, package_identifier: Optional[str] = None
) -> Tuple[bool, Optional[int], str]:
    """Return (compatible, packaging_id, reason), never selecting among duplicates."""
    unit = normalize_unit(requested_unit)
    if package_identifier:
        matches = [
            pkg for pkg in product.packagings
            if package_identifier in (pkg.package_code, pkg.packaging_barcode)
        ]
        if len(matches) == 1:
            if unit != "unknown" and not _matches_unit(product, matches[0], unit):
                return False, None, "Packaging identifier conflicts with requested unit"
            return True, matches[0].id, "Exact packaging code or barcode"
        if len(matches) > 1:
            return False, None, "Ambiguous packaging code or barcode"

    if unit == "unknown":
        return False, None, "Unknown requested unit"

    if unit in {"piece", "kg"}:
        return True, None, "Directly requested measurement"

    if unit == normalize_unit(product.unit):
        return True, None, "Product base unit"

    matches = [pkg for pkg in product.packagings if _matches_unit(product, pkg, unit)]
    if len(matches) == 1:
        return True, matches[0].id, "Unique matching packaging"
    if len(matches) > 1:
        return False, None, "Multiple matching packagings"
    return False, None, "No matching packaging"
