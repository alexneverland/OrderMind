from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
from typing import List, Optional

from backend.app.core.database import get_db
from backend.app.models.product import Product, Packaging
from backend.app.models.company import Company
from backend.app.schemas.master_data import ProductCreate, ProductResponse

router = APIRouter(prefix="/products", tags=["Products"])


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    """Create a single product manually for a company."""
    company = db.get(Company, payload.company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with id {payload.company_id} not found"
        )

    # Check unique constraint (company_id, sku)
    existing = db.execute(
        select(Product).where(
            Product.company_id == payload.company_id,
            Product.sku == payload.sku.strip()
        )
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product SKU '{payload.sku}' already exists for company {payload.company_id}"
        )

    product = Product(
        company_id=payload.company_id,
        sku=payload.sku.strip(),
        description=payload.description.strip(),
        barcode=payload.barcode.strip() if payload.barcode else None,
        unit=payload.unit.strip() if payload.unit else "piece",
        active=payload.active
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("", response_model=List[ProductResponse])
def list_products(
    company_id: int = Query(..., description="Company ID to filter products"),
    search: Optional[str] = Query(None, description="Search query for SKU, description, or barcode"),
    active_only: bool = Query(True, description="Filter only active products"),
    db: Session = Depends(get_db)
):
    """Retrieve products with their packaging configurations and aliases."""
    query = (
        select(Product)
        .options(
            joinedload(Product.packagings),
            joinedload(Product.global_aliases)
        )
        .where(Product.company_id == company_id)
    )
    if active_only:
        query = query.where(Product.active.is_(True))
    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            (Product.sku.ilike(term)) |
            (Product.description.ilike(term)) |
            (Product.barcode.ilike(term))
        )
    query = query.order_by(Product.sku.asc())
    results = db.execute(query).unique().scalars().all()
    return results
