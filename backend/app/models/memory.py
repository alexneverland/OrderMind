from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, Index, func
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


class CustomerProductAlias(Base):
    """
    Customer-specific learned product alias.
    If Customer 4531 writes 'κόκκινο' -> SKU 7843.
    Unique per customer and normalized phrase.
    """
    __tablename__ = "customer_product_aliases"
    __table_args__ = (
        UniqueConstraint("customer_id", "normalized_phrase", name="uq_customer_normalized_alias"),
        Index("ix_customer_alias_lookup", "customer_id", "normalized_phrase"),
        ForeignKeyConstraint(["customer_id", "company_id"], ["customers.id", "customers.company_id"], ondelete="CASCADE", name="fk_customer_alias_customer_company"),
        ForeignKeyConstraint(["product_id", "company_id"], ["products.id", "products.company_id"], ondelete="RESTRICT", name="fk_customer_alias_product_company"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    original_phrase = Column(String(255), nullable=False)
    normalized_phrase = Column(String(255), nullable=False)
    confirmed_count = Column(Integer, default=1, nullable=False)
    corrected_count = Column(Integer, default=0, nullable=False)
    last_confirmed_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    # Relationships
    customer = relationship("Customer", back_populates="aliases", foreign_keys=[customer_id])
    product = relationship("Product", back_populates="customer_aliases", foreign_keys=[product_id])


class HumanCorrection(Base):
    """
    Audit log of every operator correction.
    Used for feedback loop, analytics, and training.
    """
    __tablename__ = "human_corrections"
    __table_args__ = (
        ForeignKeyConstraint(["customer_id", "company_id"], ["customers.id", "customers.company_id"], ondelete="RESTRICT", name="fk_correction_customer_company"),
        ForeignKeyConstraint(["order_id", "company_id"], ["orders.id", "orders.company_id"], ondelete="RESTRICT", name="fk_correction_order_company"),
        ForeignKeyConstraint(["order_line_id", "company_id"], ["order_lines.id", "order_lines.company_id"], ondelete="RESTRICT", name="fk_correction_line_company"),
        ForeignKeyConstraint(["suggested_product_id", "company_id"], ["products.id", "products.company_id"], ondelete="RESTRICT", name="fk_correction_suggested_company"),
        ForeignKeyConstraint(["correct_product_id", "company_id"], ["products.id", "products.company_id"], ondelete="RESTRICT", name="fk_correction_correct_company"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    order_line_id = Column(Integer, ForeignKey("order_lines.id", ondelete="SET NULL"), nullable=True, index=True)
    original_phrase = Column(String(255), nullable=False)
    suggested_product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    correct_product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    notes = Column(String(500), nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    customer = relationship("Customer", back_populates="corrections", foreign_keys=[customer_id])
    order = relationship("Order", back_populates="corrections", foreign_keys=[order_id])
    order_line = relationship("OrderLine", back_populates="corrections", foreign_keys=[order_line_id])
    suggested_product = relationship("Product", foreign_keys=[suggested_product_id])
    correct_product = relationship("Product", foreign_keys=[correct_product_id])
