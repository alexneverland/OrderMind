from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import List, Optional

from backend.app.core.database import get_db
from backend.app.models.customer import Customer
from backend.app.models.company import Company
from backend.app.schemas.master_data import CustomerCreate, CustomerResponse

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    """Create a customer manually for a company."""
    company = db.get(Company, payload.company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with id {payload.company_id} not found"
        )

    # Check unique constraint (company_id, customer_code)
    existing = db.execute(
        select(Customer).where(
            Customer.company_id == payload.company_id,
            Customer.customer_code == payload.customer_code.strip()
        )
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Customer with code '{payload.customer_code}' already exists for company {payload.company_id}"
        )

    customer = Customer(
        company_id=payload.company_id,
        customer_code=payload.customer_code.strip(),
        customer_name=payload.customer_name.strip(),
        email=payload.email.strip() if payload.email else None,
        phone=payload.phone.strip() if payload.phone else None,
        active=payload.active
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("", response_model=List[CustomerResponse])
def list_customers(
    company_id: int = Query(..., description="Company ID to filter customers"),
    search: Optional[str] = Query(None, description="Search query for name or code"),
    active_only: bool = Query(True, description="Filter only active customers"),
    db: Session = Depends(get_db)
):
    """Retrieve customers for a given company."""
    query = select(Customer).where(Customer.company_id == company_id)
    if active_only:
        query = query.where(Customer.active.is_(True))
    if search:
        search_term = f"%{search.strip()}%"
        query = query.where(
            (Customer.customer_name.ilike(search_term)) |
            (Customer.customer_code.ilike(search_term))
        )
    query = query.order_by(Customer.customer_name.asc())
    return db.execute(query).scalars().all()
