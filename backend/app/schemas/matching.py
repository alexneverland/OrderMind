from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from enum import Enum


class MatchDecision(str, Enum):
    AUTO_ACCEPT = "auto_accept"
    NEEDS_REVIEW = "needs_review"
    UNRESOLVED = "unresolved"


class MatchEvidence(BaseModel):
    evidence_type: str = Field(..., description="e.g. exact_sku, exact_barcode, customer_alias_exact, fuzzy_description")
    score: float = Field(..., ge=0.0, le=1.0)
    detail: str = Field(..., description="Human-readable explanation of this evidence")


class MatchedProductInfo(BaseModel):
    product_id: int
    sku: str
    description: str
    barcode: Optional[str] = None
    unit: str = "piece"


class MatchCandidateDto(BaseModel):
    product_id: int
    sku: str
    description: str
    barcode: Optional[str] = None
    rank: int = 1
    score: float = 0.0
    evidence: List[MatchEvidence] = Field(default_factory=list)


class ConfidenceResult(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0, description="Normalized confidence score between 0.0 and 1.0")
    decision: MatchDecision = Field(..., description="auto_accept, needs_review, or unresolved")
    reasons: List[str] = Field(default_factory=list, description="List of positive and negative explainability reasons")


class LineMatchResult(BaseModel):
    line_number: int
    original_text: str
    product_phrase: str
    quantity: float
    unit: str
    raw_unit: Optional[str] = None
    unit_explicit: bool = False
    best_match: Optional[MatchedProductInfo] = None
    confidence: ConfidenceResult
    alternatives: List[MatchCandidateDto] = Field(default_factory=list)


from backend.app.schemas.order import NormalizedOrderLine


class OrderMatchRequest(BaseModel):
    company_id: int
    customer_id: int
    text: Optional[str] = None
    items: Optional[List[NormalizedOrderLine]] = None
    source_type: str = "plain_text"



class OrderMatchResponse(BaseModel):
    company_id: int
    customer_id: int
    raw_input: str
    lines: List[LineMatchResult]
    total_lines: int
    auto_accepted_count: int
    needs_review_count: int
    unresolved_count: int


class ConfirmMatchRequest(BaseModel):
    customer_id: int
    product_id: int
    original_phrase: str
    order_id: Optional[int] = None
    line_id: Optional[int] = None


class ConfirmMatchResponse(BaseModel):
    status: str = "confirmed"
    customer_id: int
    product_id: int
    original_phrase: str
    confirmed_count: int
    corrected_count: int


class CorrectMatchRequest(BaseModel):
    customer_id: int
    suggested_product_id: Optional[int] = None
    correct_product_id: int
    original_phrase: str
    order_id: Optional[int] = None
    line_id: Optional[int] = None
    notes: Optional[str] = None


class CorrectMatchResponse(BaseModel):
    status: str = "corrected"
    correction_id: int
    customer_id: int
    suggested_product_id: Optional[int] = None
    correct_product_id: int
    original_phrase: str
    confirmed_count: int
    corrected_count: int
