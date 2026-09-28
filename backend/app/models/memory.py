from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint, Index, func
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


class CustomerProductAlias(Base):
    """
    Customer-specific learned product alias.
    If Customer 4531 writes 'κόκκινο' -> SKU 7843.
    Unique per customer and normalized phrase.
    """
    __tablename__ = "customer_product_aliases"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    original_phrase = Column(String(255), nullable=False)
    normalized_phrase = Column(String(255), nullable=False)
    confirmed_count = Column(Integer, default=1, nullable=False)
    corrected_count = Column(Integer, default=0, nullable=False)
    last_confirmed_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("customer_id", "normalized_phrase", name="uq_customer_normalized_alias"),
        Index("ix_customer_alias_lookup", "customer_id", "normalized_phrase"),
    )

    # Relationships
    customer = relationship("Customer", back_populates="aliases")
    product = relationship("Product", back_populates="customer_aliases")


class HumanCorrection(Base):
    """
    Audit log of every operator correction.
    Used for feedback loop, analytics, and training.
    """
    __tablename__ = "human_corrections"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    order_line_id = Column(Integer, ForeignKey("order_lines.id", ondelete="SET NULL"), nullable=True, index=True)
    original_phrase = Column(String(255), nullable=False)
    suggested_product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    correct_product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    notes = Column(String(500), nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    customer = relationship("Customer", back_populates="corrections")
    order = relationship("Order", back_populates="corrections")
    order_line = relationship("OrderLine", back_populates="corrections")
    suggested_product = relationship("Product", foreign_keys=[suggested_product_id])
    correct_product = relationship("Product", foreign_keys=[correct_product_id])
