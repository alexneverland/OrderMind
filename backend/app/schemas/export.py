from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional
from datetime import datetime
from enum import Enum
from backend.app.schemas.pallet import PalletConfig


class ExportFormat(str, Enum):
    EXCEL = "excel"
    XLSX = "xlsx"
    CSV = "csv"
    JSON = "json"
    ORDER_SHEET = "order_sheet"


class MappingType(str, Enum):
    SOURCE_FIELD = "source_field"
    CONSTANT = "constant"


class ExportFieldMappingCreate(BaseModel):
    column_order: int = Field(..., ge=1, description="1-indexed sequence order of column")
    output_column_name: str = Field(..., min_length=1, description="Header name in exported file")
    mapping_type: MappingType = Field(default=MappingType.SOURCE_FIELD, description="source_field or constant")
    source_field: Optional[str] = Field(default=None, description="Whitelisted source field, e.g. customer.customer_code, line.sku")
    constant_value: Optional[str] = Field(default=None, description="Literal constant value if mapping_type is constant")


class ExportFieldMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    export_profile_id: int
    column_order: int
    output_column_name: str
    mapping_type: str
    source_field: Optional[str] = None
    constant_value: Optional[str] = None


class ExportProfileCreate(BaseModel):
    company_id: int
    name: str = Field(..., min_length=1, description="Friendly profile name e.g. SoftOne ERP, Warehouse Excel")
    format: str = Field(default="xlsx", description="xlsx, excel, csv, or json")
    delimiter: str = Field(default=",", min_length=1, max_length=1, description="Single-character delimiter for CSV format")
    include_header: bool = Field(default=True, description="Whether to write header row in Excel/CSV")
    encoding: str = Field(default="utf-8-sig", description="Encoding for CSV: utf-8, utf-8-sig")
    mappings: List[ExportFieldMappingCreate] = Field(default_factory=list, description="List of column mappings; empty for the fixed four-column order sheet")
    bonus_separate_row: bool = False
    bonus_marker: Optional[str] = Field(default=None, max_length=20)
    quantity_output_unit: str = "source"
    convert_case_using_pieces_per_case: bool = False
    palletization: PalletConfig = Field(default_factory=PalletConfig)


class ExportProfileUpdate(BaseModel):
    name: Optional[str] = None
    format: Optional[str] = None
    delimiter: Optional[str] = Field(default=None, min_length=1, max_length=1)
    include_header: Optional[bool] = None
    encoding: Optional[str] = None
    mappings: Optional[List[ExportFieldMappingCreate]] = None
    bonus_separate_row: Optional[bool] = None
    bonus_marker: Optional[str] = Field(default=None, max_length=20)
    quantity_output_unit: Optional[str] = None
    convert_case_using_pieces_per_case: Optional[bool] = None
    palletization: PalletConfig | None = None


class ExportProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    name: str
    format: str
    delimiter: str
    include_header: bool
    encoding: str
    bonus_separate_row: bool
    bonus_marker: Optional[str]
    quantity_output_unit: str
    convert_case_using_pieces_per_case: bool
    palletization: PalletConfig
    created_at: datetime
    field_mappings: List[ExportFieldMappingResponse] = Field(default_factory=list)
