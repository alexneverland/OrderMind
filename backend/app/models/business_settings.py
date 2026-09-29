from sqlalchemy import Boolean, Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint, func
from backend.app.core.database import Base


class CompanyBusinessSettings(Base):
    __tablename__ = "company_business_settings"

    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    bonus_enabled = Column(Boolean, nullable=False, default=False, server_default="0")
    bonus_expression_mode = Column(String(24), nullable=False, default="disabled", server_default="disabled")
    unitless_order_behavior = Column(String(32), nullable=False, default="require_review", server_default="require_review")
    allow_packaging_conversion = Column(Boolean, nullable=False, default=False, server_default="0")
    learn_unit_preferences = Column(Boolean, nullable=False, default=False, server_default="0")


class CompanyRule(Base):
    """Validated, company-owned deterministic promotion configuration."""
    __tablename__ = "company_rules"
    __table_args__ = (
        UniqueConstraint("company_id", "fingerprint", name="uq_company_rule_fingerprint"),
        ForeignKeyConstraint(["product_id", "company_id"], ["products.id", "products.company_id"], name="fk_company_rule_product_company", ondelete="RESTRICT"),
        ForeignKeyConstraint(["customer_id", "company_id"], ["customers.id", "customers.company_id"], name="fk_company_rule_customer_company", ondelete="RESTRICT"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_type = Column(String(40), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    product_id = Column(Integer, nullable=True)
    customer_id = Column(Integer, nullable=True)
    configuration = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
