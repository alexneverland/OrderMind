from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.schemas.export import (
    ExportProfileCreate,
    ExportProfileUpdate,
    ExportProfileResponse,
)
from backend.app.services.export_profile_service import (
    ExportProfileService,
    ExportProfileValidationError,
)
from backend.app.services.export_registry import AVAILABLE_SOURCE_FIELDS

router = APIRouter(prefix="/export-profiles", tags=["Export Profiles"])


@router.get("/source-fields", response_model=dict[str, str])
def list_export_source_fields():
    return AVAILABLE_SOURCE_FIELDS


@router.post("", response_model=ExportProfileResponse, status_code=status.HTTP_201_CREATED)
def create_export_profile(
    payload: ExportProfileCreate,
    db: Session = Depends(get_db)
):
    try:
        profile = ExportProfileService.create_profile(db=db, payload=payload)
        return profile
    except (ExportProfileValidationError, ValueError) as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )


@router.get("", response_model=List[ExportProfileResponse])
def list_export_profiles(
    company_id: Optional[int] = Query(None, description="Filter profiles by company ID"),
    db: Session = Depends(get_db)
):
    return ExportProfileService.list_profiles(db=db, company_id=company_id)


@router.get("/{id}", response_model=ExportProfileResponse)
def get_export_profile(
    id: int,
    db: Session = Depends(get_db)
):
    profile = ExportProfileService.get_profile(db=db, profile_id=id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export profile with id {id} not found"
        )
    return profile


@router.put("/{id}", response_model=ExportProfileResponse)
def update_export_profile(
    id: int,
    payload: ExportProfileUpdate,
    db: Session = Depends(get_db)
):
    try:
        profile = ExportProfileService.update_profile(db=db, profile_id=id, payload=payload)
        return profile
    except ExportProfileValidationError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(ve)
        )


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_export_profile(
    id: int,
    db: Session = Depends(get_db)
):
    success = ExportProfileService.delete_profile(db=db, profile_id=id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export profile with id {id} not found"
        )
    return None
