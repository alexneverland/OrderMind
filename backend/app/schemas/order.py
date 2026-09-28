from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from backend.app.core.text_normalizer import normalize_unit


class NormalizedOrderLineDraft(BaseModel):
    """Extraction draft item produced by AI or mock parser."""
    original_text: str = Field(..., description="Verbatim fragment from input representing this item")
    product_phrase: str = Field(..., description="Extracted product description or keyword phrase without quantities/units")
    quantity: float = Field(..., gt=0, description="Requested quantity, must be positive")
    unit: str = Field(default="piece", description="Normalized packaging or unit of measure")

    @field_validator("unit", mode="before")
    @classmethod
    def canonicalize_unit(cls, v: Optional[str]) -> str:
        return normalize_unit(v)

    @field_validator("product_phrase", mode="before")
    @classmethod
    def clean_product_phrase(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("Product phrase cannot be empty")
        return str(v).strip()


class NormalizedOrderLine(BaseModel):
    """Validated, sequential order line."""
    line_number: int = Field(..., ge=1, description="Sequential line number starting at 1")
    original_text: str = Field(..., description="Verbatim line or segment from input")
    product_phrase: str = Field(..., description="Product phrase requested by customer")
    quantity: float = Field(..., gt=0, description="Quantity")
    unit: str = Field(default="piece", description="Canonical unit: piece, case, kg, pallet")

    @field_validator("unit", mode="before")
    @classmethod
    def canonicalize_unit(cls, v: Optional[str]) -> str:
        return normalize_unit(v)


class NormalizedOrder(BaseModel):
    """
    Internal canonical representation of an extracted order.
    Agnostic to ERP, specific SKUs, or matching engine details.
    """
    company_id: int
    customer_id: int
    source_type: str = "plain_text"
    raw_input: str
    items: List[NormalizedOrderLine] = Field(default_factory=list)


class OrderParseRequest(BaseModel):
    company_id: int
    customer_id: int
    source_type: str = "plain_text"
    text: str = Field(..., min_length=1, description="Raw order text to parse")


class OrderParseResponse(BaseModel):
    company_id: int
    customer_id: int
    source_type: str
    raw_input: str
    items: List[NormalizedOrderLine]
    total_items: int
