from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


class OrderSource(Base):
    """Origin of the order intake with hash for duplicate detection."""
    __tablename__ = "order_sources"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    source_type = Column(String(50), nullable=False, default="plain_text")  # plain_text, email, pdf, etc.
    raw_payload = Column(Text, nullable=False)
    sender_info = Column(String(255), nullable=True)
    original_filename = Column(String(255), nullable=True)
    mime_type = Column(String(100), nullable=True)
    source_hash = Column(String(64), nullable=True, index=True)  # SHA-256 hash for deduplication
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    orders = relationship("Order", back_populates="order_source")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    order_source_id = Column(Integer, ForeignKey("order_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    order_number = Column(String(100), nullable=False, unique=True, index=True)
    status = Column(String(50), nullable=False, default="pending_review")  # pending_review, confirmed, exported, cancelled
    overall_confidence = Column(Float, default=0.0, nullable=False)
    raw_input = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    exported_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    company = relationship("Company", back_populates="orders")
    customer = relationship("Customer", back_populates="orders")
    order_source = relationship("OrderSource", back_populates="orders")
    lines = relationship("OrderLine", back_populates="order", cascade="all, delete-orphan", order_by="OrderLine.line_number")
    corrections = relationship("HumanCorrection", back_populates="order")


class OrderLine(Base):
    __tablename__ = "order_lines"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    line_number = Column(Integer, nullable=False)
    original_text = Column(String(500), nullable=False)
    product_phrase = Column(String(500), nullable=False)
    requested_quantity = Column(Float, nullable=False, default=1.0)
    requested_unit = Column(String(50), nullable=False, default="piece")
    
    # Matching output
    matched_product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    matched_packaging_id = Column(Integer, ForeignKey("packagings.id", ondelete="SET NULL"), nullable=True)
    final_sku = Column(String(100), nullable=True)
    final_quantity = Column(Float, nullable=True)
    final_unit = Column(String(50), nullable=True)

    # Confidence and explainability (JSON-compatible database type)
    confidence_score = Column(Float, default=0.0, nullable=False)
    confidence_reasons = Column(JSON, nullable=False, default=list)  # e.g. ["+ Customer alias match", "+ Packaging match"]
    status = Column(String(50), default="needs_review", nullable=False)  # matched, needs_review, confirmed, manual_override

    # Relationships
    order = relationship("Order", back_populates="lines")
    matched_product = relationship("Product")
    matched_packaging = relationship("Packaging")
    candidates = relationship("MatchCandidate", back_populates="order_line", cascade="all, delete-orphan", order_by="MatchCandidate.rank")


class MatchCandidate(Base):
    __tablename__ = "match_candidates"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    order_line_id = Column(Integer, ForeignKey("order_lines.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    rank = Column(Integer, nullable=False)
    match_type = Column(String(50), nullable=False)  # exact_sku, barcode, customer_alias, global_alias, fuzzy_text, semantic
    score = Column(Float, nullable=False)
    explanation = Column(String(500), nullable=False)

    # Relationships
    order_line = relationship("OrderLine", back_populates="candidates")
    product = relationship("Product")
