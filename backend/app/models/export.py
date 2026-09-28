from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


class ExportProfile(Base):
    __tablename__ = "export_profiles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    format = Column(String(50), nullable=False, default="excel")  # excel, csv, json
    delimiter = Column(String(10), default=",")
    include_header = Column(Boolean, default=True, nullable=False)
    encoding = Column(String(20), default="utf-8-sig", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    company = relationship("Company", back_populates="export_profiles")
    field_mappings = relationship("ExportFieldMapping", back_populates="export_profile", cascade="all, delete-orphan", order_by="ExportFieldMapping.column_order")


class ExportFieldMapping(Base):
    __tablename__ = "export_field_mappings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    export_profile_id = Column(Integer, ForeignKey("export_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    column_order = Column(Integer, nullable=False, default=0)
    output_column_name = Column(String(100), nullable=False)
    mapping_type = Column(String(50), nullable=False, default="source_field")  # source_field, constant, computed
    source_field = Column(String(100), nullable=True)  # e.g. customer_code, sku, quantity, unit
    constant_value = Column(String(255), nullable=True)  # e.g. "01" for warehouse

    # Relationships
    export_profile = relationship("ExportProfile", back_populates="field_mappings")


class ExportRecord(Base):
    """Audit record for every generated order export file."""
    __tablename__ = "export_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    export_profile_id = Column(Integer, ForeignKey("export_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    format = Column(String(50), nullable=False)
    filename = Column(String(255), nullable=False)
    content_hash = Column(String(64), nullable=True)  # SHA-256 of generated file content
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    order = relationship("Order", back_populates="export_records")
    export_profile = relationship("ExportProfile")
