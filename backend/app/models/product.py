from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, UniqueConstraint, Index, func
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(100), nullable=False, index=True)
    description = Column(String(500), nullable=False, index=True)
    barcode = Column(String(100), nullable=True, index=True)
    unit = Column(String(50), nullable=False, default="piece")
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "sku", name="uq_company_product_sku"),
    )

    # Relationships
    company = relationship("Company", back_populates="products")
    packagings = relationship("Packaging", back_populates="product", cascade="all, delete-orphan")
    global_aliases = relationship("ProductAlias", back_populates="product", cascade="all, delete-orphan")
    customer_aliases = relationship("CustomerProductAlias", back_populates="product", cascade="all, delete-orphan")


class ProductAlias(Base):
    """Global aliases for products valid across all customers for a given company."""
    __tablename__ = "product_aliases"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    original_phrase = Column(String(255), nullable=False)
    normalized_phrase = Column(String(255), nullable=False, index=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "product_id", "normalized_phrase", name="uq_company_product_global_alias"),
        Index("ix_product_alias_lookup", "company_id", "normalized_phrase"),
    )

    # Relationships
    company = relationship("Company", back_populates="global_aliases")
    product = relationship("Product", back_populates="global_aliases")


class Packaging(Base):
    __tablename__ = "packagings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    package_code = Column(String(100), nullable=True, index=True)  # Specific packaging code (not generic SKU)
    packaging_barcode = Column(String(100), nullable=True, index=True)
    package_type = Column(String(100), nullable=False)  # e.g. "case", "box", "shrink", "pallet"
    pieces_per_case = Column(Float, nullable=False, default=1.0)
    weight = Column(Float, nullable=True)
    unit = Column(String(50), nullable=False, default="piece")

    # Relationships
    product = relationship("Product", back_populates="packagings")
