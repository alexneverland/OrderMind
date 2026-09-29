from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import List

from backend.app.core.database import get_db
from backend.app.models.company import Company
from backend.app.models.business_settings import CompanyBusinessSettings
from backend.app.schemas.business_settings import BusinessSettingsValues, BusinessSettingsResponse
from backend.app.services.business_settings_service import effective_business_settings
from backend.app.schemas.company import CompanyCreate, CompanyResponse

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    """Create a new tenant / business company."""
    company = Company(
        name=payload.name.strip(),
        tax_id=payload.tax_id.strip() if payload.tax_id else None
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.get("", response_model=List[CompanyResponse])
def list_companies(db: Session = Depends(get_db)):
    """List all companies."""
    stmt = select(Company).order_by(Company.created_at.desc())
    return db.execute(stmt).scalars().all()


@router.get("/{company_id}", response_model=CompanyResponse)
def get_company(company_id: int, db: Session = Depends(get_db)):
    """Retrieve details for a specific company."""
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with id {company_id} not found"
        )
    return company


@router.get("/{company_id}/business-settings", response_model=BusinessSettingsResponse)
def get_business_settings(company_id: int, db: Session = Depends(get_db)):
    if not db.get(Company, company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    return effective_business_settings(db, company_id)


@router.put("/{company_id}/business-settings", response_model=BusinessSettingsResponse)
def put_business_settings(company_id: int, payload: BusinessSettingsValues, db: Session = Depends(get_db)):
    if not db.get(Company, company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    row = db.get(CompanyBusinessSettings, company_id)
    if row is None:
        row = CompanyBusinessSettings(company_id=company_id)
        db.add(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row
