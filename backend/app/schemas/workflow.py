from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Any
from datetime import datetime
from enum import Enum

from backend.app.schemas.matching import LineMatchResult


class OrderStatus(str, Enum):
    DRAFT = "draft"
    PROCESSING = "processing"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    EXPORTED = "exported"
    CANCELLED = "cancelled"


class OrderLineStatus(str, Enum):
    AUTO_ACCEPTED = "auto_accepted"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    UNRESOLVED = "unresolved"


class OrderCandidateDto(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    product_id: int
    rank: int
    match_type: str
    score: float
    explanation: str


class OrderLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    line_number: int
    original_text: str
    product_phrase: str
    requested_quantity: float
    requested_unit: str
    raw_unit: Optional[str] = None
    unit_explicit: bool = False
    matched_product_id: Optional[int] = None
    matched_packaging_id: Optional[int] = None
    final_sku: Optional[str] = None
    final_quantity: Optional[float] = None
    final_unit: Optional[str] = None
    confidence_score: float = 0.0
    confidence_reasons: List[str] = Field(default_factory=list)
    status: str
    candidates: List[OrderCandidateDto] = Field(default_factory=list)


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    customer_id: int
    order_number: str
    status: str
    overall_confidence: float
    raw_input: str
    created_at: datetime
    confirmed_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    exported_at: Optional[datetime] = None
    lines: List[OrderLineResponse] = Field(default_factory=list)


class OrderApprovalResponse(BaseModel):
    order_id: int
    status: str
    total_lines: int
    approved_lines: int
    pending_review_lines: int
    unresolved_lines: int


class OrderLineUpdateValuesRequest(BaseModel):
    final_quantity: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)
    final_unit: Optional[str] = None


class CreateOrderFromMatchRequest(BaseModel):
    company_id: int
    customer_id: int
    order_number: Optional[str] = None
    idempotency_key: Optional[str] = None
    source_type: str = "plain_text"
    text: Optional[str] = None
    raw_input: Optional[str] = None
    items: Optional[List[Any]] = None
    lines: Optional[List[Any]] = None


class CanonicalOrderItem(BaseModel):
    line_number: int
    sku: str
    description: str
    quantity: float
    unit: str
    barcode: Optional[str] = None
    original_text: str
    requested_quantity: float
    requested_unit: str


class CanonicalOrderCustomer(BaseModel):
    id: int
    customer_code: str
    customer_name: str


class CanonicalOrder(BaseModel):
    order_id: int
    order_number: str
    company_id: int
    customer: CanonicalOrderCustomer
    status: str
    created_at: str
    approved_at: Optional[str] = None
    items: List[CanonicalOrderItem] = Field(default_factory=list)
