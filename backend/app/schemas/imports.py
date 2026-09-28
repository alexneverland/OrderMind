from pydantic import BaseModel
from typing import Dict, List, Any, Optional


class RowErrorDetail(BaseModel):
    row_number: int
    field: Optional[str] = None
    reason: str
    raw_data: Optional[Dict[str, Any]] = None


class HeaderPreviewResponse(BaseModel):
    entity_type: str
    available_columns: List[str]
    total_preview_rows: int
    preview_rows: List[Dict[str, Any]]
    suggested_mapping: Dict[str, str]  # target_field -> excel_column
    supported_target_fields: List[str]
    required_target_fields: List[str]


class ImportSummaryResponse(BaseModel):
    entity_type: str
    total_rows: int
    imported: int
    skipped: int
    errors: int
    error_details: List[RowErrorDetail] = []
