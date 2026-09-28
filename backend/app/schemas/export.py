from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional
from datetime import datetime
from enum import Enum


class ExportFormat(str, Enum):
    EXCEL = "excel"
    XLSX = "xlsx"
    CSV = "csv"
    JSON = "json"


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
    delimiter: str = Field(default=",", description="Delimiter for CSV format: ',', ';', '\t', '|'")
    include_header: bool = Field(default=True, description="Whether to write header row in Excel/CSV")
    encoding: str = Field(default="utf-8-sig", description="Encoding for CSV: utf-8, utf-8-sig")
    mappings: List[ExportFieldMappingCreate] = Field(..., min_length=1, description="List of column mappings")


class ExportProfileUpdate(BaseModel):
    name: Optional[str] = None
    format: Optional[str] = None
    delimiter: Optional[str] = None
    include_header: Optional[bool] = None
    encoding: Optional[str] = None
    mappings: Optional[List[ExportFieldMappingCreate]] = None


class ExportProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    name: str
    format: str
    delimiter: str
    include_header: bool
    encoding: str
    created_at: datetime
    field_mappings: List[ExportFieldMappingResponse] = Field(default_factory=list)
