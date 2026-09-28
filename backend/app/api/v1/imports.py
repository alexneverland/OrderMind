import json
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from typing import Dict, Any

from backend.app.core.database import get_db
from backend.app.models.company import Company
from backend.app.schemas.imports import HeaderPreviewResponse, ImportSummaryResponse
from backend.app.services.master_data_service import MasterDataService

router = APIRouter(prefix="/imports", tags=["Master Data Imports"])


def _parse_mapping(mapping_str: str) -> Dict[str, str]:
    """Safely parse mapping json string to dictionary."""
    try:
        data = json.loads(mapping_str)
        if not isinstance(data, dict):
            raise ValueError("Mapping must be a key-value dictionary")
        return {str(k).strip(): str(v).strip() for k, v in data.items() if v}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON mapping format: {str(e)}"
        )


@router.post("/preview", response_model=HeaderPreviewResponse)
async def preview_import_file(
    file: UploadFile = File(..., description="Excel file to preview (.xlsx / .xls)"),
    entity_type: str = Form(..., description="Entity type: 'customers', 'products', or 'packaging'")
):
    """
    Reads an uploaded Excel file headers and sample rows, suggesting probable column mappings.
    """
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be an Excel spreadsheet (.xlsx or .xls)"
        )

    content = await file.read()
    try:
        preview = MasterDataService.preview_excel(content, entity_type.strip().lower())
        return preview
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to preview Excel file: {str(e)}"
        )


@router.post("/customers", response_model=ImportSummaryResponse)
async def import_customers_endpoint(
    company_id: int = Form(..., description="Target Company ID"),
    mapping: str = Form(..., description="JSON string mapping target fields to Excel column names"),
    file: UploadFile = File(..., description="Excel file containing customers"),
    db: Session = Depends(get_db)
):
    """
    Imports customers for a company applying validated column mappings.
    """
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with id {company_id} not found"
        )

    mapping_dict = _parse_mapping(mapping)
    content = await file.read()

    try:
        summary = MasterDataService.import_customers(
            db=db,
            company_id=company_id,
            file_bytes=content,
            mapping=mapping_dict
        )
        return summary
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Customer import failed: {str(e)}"
        )


@router.post("/products", response_model=ImportSummaryResponse)
async def import_products_endpoint(
    company_id: int = Form(..., description="Target Company ID"),
    mapping: str = Form(..., description="JSON string mapping target fields to Excel column names"),
    file: UploadFile = File(..., description="Excel file containing products"),
    db: Session = Depends(get_db)
):
    """
    Imports products for a company applying validated column mappings.
    """
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with id {company_id} not found"
        )

    mapping_dict = _parse_mapping(mapping)
    content = await file.read()

    try:
        summary = MasterDataService.import_products(
            db=db,
            company_id=company_id,
            file_bytes=content,
            mapping=mapping_dict
        )
        return summary
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Product import failed: {str(e)}"
        )


@router.post("/packaging", response_model=ImportSummaryResponse)
async def import_packaging_endpoint(
    company_id: int = Form(..., description="Target Company ID"),
    mapping: str = Form(..., description="JSON string mapping target fields to Excel column names"),
    file: UploadFile = File(..., description="Excel file containing packaging definitions"),
    db: Session = Depends(get_db)
):
    """
    Imports packaging configurations linked to existing company products.
    """
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with id {company_id} not found"
        )

    mapping_dict = _parse_mapping(mapping)
    content = await file.read()

    try:
        summary = MasterDataService.import_packaging(
            db=db,
            company_id=company_id,
            file_bytes=content,
            mapping=mapping_dict
        )
        return summary
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Packaging import failed: {str(e)}"
        )
