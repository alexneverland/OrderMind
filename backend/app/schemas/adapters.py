from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class NormalizedInput(BaseModel):
    """
    Standardized normalized input representation across all channels.
    Crucial guarantee: raw_text is never modified or stripped.
    """
    source_type: str = Field(default="plain_text", description="Input channel type")
    raw_text: str = Field(..., description="Original unaltered raw text")
    normalized_text: str = Field(..., description="Cleaned and normalized text for parsing")
    sender_email: Optional[str] = None
    sender_phone: Optional[str] = None
    original_filename: Optional[str] = None
    mime_type: str = "text/plain"
    source_hash: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
