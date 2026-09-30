from sqlalchemy import Column, Integer, String, Boolean, Float, Numeric, DateTime, ForeignKey, UniqueConstraint, ForeignKeyConstraint, Index, func, event
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(100), nullable=False, index=True)
    description = Column(String(500), nullable=False, index=True)
    normalized_description = Column(String(500), nullable=False, server_default="")
    stemmed_description = Column(String(500), nullable=False, server_default="")
    barcode = Column(String(100), nullable=True, index=True)
    unit = Column(String(50), nullable=False, default="piece")
    kg_per_piece = Column(Numeric(16, 6), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "sku", name="uq_company_product_sku"),
        UniqueConstraint("id", "company_id", name="uq_products_id_company_id"),
        Index("ix_products_company_normalized_description", "company_id", "normalized_description"),
        Index("ix_products_company_stemmed_description", "company_id", "stemmed_description"),
    )

    # Relationships
    company = relationship("Company", back_populates="products")
    packagings = relationship("Packaging", back_populates="product", cascade="all, delete-orphan", foreign_keys="Packaging.product_id")
    global_aliases = relationship(
        "ProductAlias",
        back_populates="product",
        cascade="all, delete-orphan",
        primaryjoin="and_(Product.id==ProductAlias.product_id, Product.company_id==ProductAlias.company_id)",
        overlaps="company,global_aliases"
    )
    customer_aliases = relationship("CustomerProductAlias", back_populates="product", cascade="all, delete-orphan", foreign_keys="CustomerProductAlias.product_id")


class ProductAlias(Base):
    """Global aliases for products valid across all customers for a given company."""
    __tablename__ = "product_aliases"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    original_phrase = Column(String(255), nullable=False)
    normalized_phrase = Column(String(255), nullable=False, index=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "product_id", "normalized_phrase", name="uq_company_product_global_alias"),
        Index("ix_product_alias_lookup", "company_id", "normalized_phrase"),
        ForeignKeyConstraint(["product_id", "company_id"], ["products.id", "products.company_id"], ondelete="CASCADE", name="fk_product_alias_product_company"),
    )

    # Relationships
    company = relationship("Company", back_populates="global_aliases", overlaps="global_aliases,product")
    product = relationship(
        "Product",
        back_populates="global_aliases",
        primaryjoin="and_(Product.id==ProductAlias.product_id, Product.company_id==ProductAlias.company_id)",
        overlaps="company,global_aliases"
    )


class Packaging(Base):
    __tablename__ = "packagings"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_packagings_id_company_id"),
        ForeignKeyConstraint(["product_id", "company_id"], ["products.id", "products.company_id"], ondelete="CASCADE", name="fk_packaging_product_company"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    package_code = Column(String(100), nullable=True, index=True)  # Specific packaging code (not generic SKU)
    packaging_barcode = Column(String(100), nullable=True, index=True)
    package_type = Column(String(100), nullable=False)  # e.g. "case", "box", "shrink", "pallet"
    pieces_per_case = Column(Float, nullable=False, default=1.0)
    weight = Column(Float, nullable=True)
    kg_per_case = Column(Numeric(16, 6), nullable=True)
    unit = Column(String(50), nullable=False, default="piece")

    # Relationships
    product = relationship("Product", back_populates="packagings", foreign_keys=[product_id])


@event.listens_for(Product, "before_insert")
@event.listens_for(Product, "before_update")
def normalize_product_description(mapper, connection, target):
    from backend.app.core.text_normalizer import normalize_text, stem_phrase

    target.normalized_description = normalize_text(target.description)
    target.stemmed_description = stem_phrase(target.normalized_description)
