from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
from typing import List, Optional

from backend.app.core.database import get_db
from backend.app.models.product import Product, Packaging
from backend.app.models.company import Company
from backend.app.schemas.master_data import ProductCreate, ProductResponse
from pydantic import BaseModel, Field


class ProductWeightUpdate(BaseModel):
    company_id: int
    kg_per_piece: float | None = Field(default=None, ge=0.000001, le=1_000_000, allow_inf_nan=False)


class PackagingWeightUpdate(BaseModel):
    company_id: int
    kg_per_case: float | None = Field(default=None, ge=0.000001, le=1_000_000, allow_inf_nan=False)

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
        kg_per_piece=payload.kg_per_piece,
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


@router.put("/{product_id}/physical-weight", response_model=ProductResponse)
def set_product_weight(product_id: int, payload: ProductWeightUpdate, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if product is None or product.company_id != payload.company_id:
        raise HTTPException(status_code=404, detail="Product not found")
    product.kg_per_piece = payload.kg_per_piece
    db.commit()
    db.refresh(product)
    return product


@router.put("/packaging/{packaging_id}/physical-weight")
def set_packaging_weight(packaging_id: int, payload: PackagingWeightUpdate, db: Session = Depends(get_db)):
    packaging = db.get(Packaging, packaging_id)
    if packaging is None or packaging.company_id != payload.company_id:
        raise HTTPException(status_code=404, detail="Packaging not found")
    packaging.kg_per_case = payload.kg_per_case
    db.commit()
    return {"id": packaging.id, "kg_per_case": packaging.kg_per_case}
