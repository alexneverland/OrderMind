from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from backend.app.core.database import Base


class CompanyBusinessSettings(Base):
    __tablename__ = "company_business_settings"

    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    bonus_enabled = Column(Boolean, nullable=False, default=False, server_default="0")
    bonus_expression_mode = Column(String(24), nullable=False, default="disabled", server_default="disabled")
    unitless_order_behavior = Column(String(32), nullable=False, default="require_review", server_default="require_review")
    allow_packaging_conversion = Column(Boolean, nullable=False, default=False, server_default="0")
    learn_unit_preferences = Column(Boolean, nullable=False, default=False, server_default="0")
