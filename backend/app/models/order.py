from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, JSON, Boolean, func, UniqueConstraint, ForeignKeyConstraint
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
    __table_args__ = (
        UniqueConstraint("company_id", "order_number", name="uq_company_order_number"),
        UniqueConstraint("company_id", "idempotency_key", name="uq_company_idempotency_key"),
        UniqueConstraint("id", "company_id", name="uq_orders_id_company_id"),
        ForeignKeyConstraint(["customer_id", "company_id"], ["customers.id", "customers.company_id"], ondelete="RESTRICT", name="fk_order_customer_company"),
        ForeignKeyConstraint(["last_export_profile_id", "company_id"], ["export_profiles.id", "export_profiles.company_id"], ondelete="RESTRICT", name="fk_order_export_profile_company"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id = Column(Integer, nullable=False, index=True)
    order_source_id = Column(Integer, ForeignKey("order_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    order_number = Column(String(100), nullable=False, index=True)
    idempotency_key = Column(String(100), nullable=True, index=True)
    idempotency_fingerprint = Column(String(64), nullable=True)
    version = Column(Integer, default=1, nullable=False)  # Optimistic concurrency version
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    status = Column(String(50), nullable=False, default="pending_review")  # draft, processing, pending_review, approved, exported, cancelled
    overall_confidence = Column(Float, default=0.0, nullable=False)
    raw_input = Column(Text, nullable=False)
    approved_snapshot = Column(JSON, nullable=True)  # Deterministic immutable snapshot at approval time
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    exported_at = Column(DateTime(timezone=True), nullable=True)
    last_export_profile_id = Column(Integer, ForeignKey("export_profiles.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    company = relationship("Company", back_populates="orders", overlaps="customer,orders")
    customer = relationship(
        "Customer",
        back_populates="orders",
        primaryjoin="and_(Customer.id==Order.customer_id, Customer.company_id==Order.company_id)",
        overlaps="company,orders"
    )
    order_source = relationship("OrderSource", back_populates="orders")
    lines = relationship("OrderLine", back_populates="order", cascade="all, delete-orphan", order_by="OrderLine.line_number", foreign_keys="OrderLine.order_id")
    corrections = relationship("HumanCorrection", back_populates="order", foreign_keys="HumanCorrection.order_id")
    last_export_profile = relationship("ExportProfile", foreign_keys=[last_export_profile_id])
    export_records = relationship("ExportRecord", back_populates="order", cascade="all, delete-orphan", order_by="desc(ExportRecord.created_at)", foreign_keys="ExportRecord.order_id")


class OrderRevision(Base):
    """A new reviewable order linked to its immutable approved predecessor."""
    __tablename__ = "order_revisions"
    __table_args__ = (
        UniqueConstraint("company_id", "request_key", name="uq_revision_request"),
        ForeignKeyConstraint(["source_order_id", "company_id"], ["orders.id", "orders.company_id"], ondelete="RESTRICT", name="fk_revision_source_company"),
        ForeignKeyConstraint(["revision_order_id", "company_id"], ["orders.id", "orders.company_id"], ondelete="CASCADE", name="fk_revision_order_company"),
    )
    revision_order_id = Column(Integer, primary_key=True)
    source_order_id = Column(Integer, nullable=False, index=True)
    company_id = Column(Integer, nullable=False)
    request_key = Column(String(36), nullable=False)


class OrderLine(Base):
    __tablename__ = "order_lines"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_order_lines_id_company_id"),
        UniqueConstraint("order_id", "line_number", name="uq_order_line_number"),
        ForeignKeyConstraint(["order_id", "company_id"], ["orders.id", "orders.company_id"], ondelete="CASCADE", name="fk_order_line_order_company"),
        ForeignKeyConstraint(["matched_product_id", "company_id"], ["products.id", "products.company_id"], ondelete="RESTRICT", name="fk_order_line_product_company"),
        ForeignKeyConstraint(["matched_packaging_id", "company_id"], ["packagings.id", "packagings.company_id"], ondelete="RESTRICT", name="fk_order_line_packaging_company"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    line_number = Column(Integer, nullable=False)
    original_text = Column(String(500), nullable=False)
    product_phrase = Column(String(500), nullable=False)
    requested_quantity = Column(Float, nullable=False, default=1.0)
    requested_unit = Column(String(50), nullable=False, default="piece")
    raw_unit = Column(String(50), nullable=True)
    unit_explicit = Column(Boolean, default=False, nullable=False)
    quantity_text = Column(String(100), nullable=True)
    bonus_quantity = Column(Float, nullable=False, default=0.0, server_default="0")
    calculated_bonus_quantity = Column(Float, nullable=False, default=0.0, server_default="0")
    promotion_result = Column(JSON, nullable=True)
    final_bonus_quantity = Column(Float, nullable=True)
    
    # Matching output
    matched_product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    matched_packaging_id = Column(Integer, ForeignKey("packagings.id", ondelete="SET NULL"), nullable=True)
    final_sku = Column(String(100), nullable=True)
    final_quantity = Column(Float, nullable=True)
    final_unit = Column(String(50), nullable=True)

    # Confidence and explainability (JSON-compatible database type)
    confidence_score = Column(Float, default=0.0, nullable=False)
    confidence_reasons = Column(JSON, nullable=False, default=list)  # e.g. ["+ Customer alias match", "+ Packaging match"]
    status = Column(String(50), default="needs_review", nullable=False)  # auto_accepted, needs_review, confirmed, corrected, unresolved

    # Relationships
    order = relationship("Order", back_populates="lines", foreign_keys=[order_id])
    matched_product = relationship("Product", foreign_keys=[matched_product_id])
    matched_packaging = relationship("Packaging", foreign_keys=[matched_packaging_id])
    candidates = relationship("MatchCandidate", back_populates="order_line", cascade="all, delete-orphan", order_by="MatchCandidate.rank", foreign_keys="MatchCandidate.order_line_id")
    corrections = relationship("HumanCorrection", back_populates="order_line", foreign_keys="HumanCorrection.order_line_id")


class MatchCandidate(Base):
    __tablename__ = "match_candidates"
    __table_args__ = (
        ForeignKeyConstraint(["order_line_id", "company_id"], ["order_lines.id", "order_lines.company_id"], ondelete="CASCADE", name="fk_match_candidate_line_company"),
        ForeignKeyConstraint(["product_id", "company_id"], ["products.id", "products.company_id"], ondelete="RESTRICT", name="fk_match_candidate_product_company"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, nullable=False, index=True)
    order_line_id = Column(Integer, ForeignKey("order_lines.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    rank = Column(Integer, nullable=False)
    match_type = Column(String(50), nullable=False)  # exact_sku, barcode, customer_alias, global_alias, fuzzy_text, semantic
    score = Column(Float, nullable=False)
    explanation = Column(String(500), nullable=False)

    # Relationships
    order_line = relationship("OrderLine", back_populates="candidates", foreign_keys=[order_line_id])
    product = relationship("Product", foreign_keys=[product_id])
