from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, func
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


class ExportProfile(Base):
    __tablename__ = "export_profiles"
    __table_args__ = (UniqueConstraint("id", "company_id", name="uq_export_profiles_id_company_id"),)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    format = Column(String(50), nullable=False, default="excel")  # excel, csv, json
    delimiter = Column(String(10), default=",")
    include_header = Column(Boolean, default=True, nullable=False)
    encoding = Column(String(20), default="utf-8-sig", nullable=False)
    bonus_separate_row = Column(Boolean, nullable=False, default=False, server_default="0")
    bonus_marker = Column(String(20), nullable=True)
    quantity_output_unit = Column(String(20), nullable=False, default="source", server_default="source")
    convert_case_using_pieces_per_case = Column(Boolean, nullable=False, default=False, server_default="0")
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
    __table_args__ = (
        ForeignKeyConstraint(["order_id", "company_id"], ["orders.id", "orders.company_id"], ondelete="CASCADE", name="fk_export_record_order_company"),
        ForeignKeyConstraint(["export_profile_id", "company_id"], ["export_profiles.id", "export_profiles.company_id"], ondelete="RESTRICT", name="fk_export_record_profile_company"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    export_profile_id = Column(Integer, ForeignKey("export_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    format = Column(String(50), nullable=False)
    filename = Column(String(255), nullable=False)
    content_hash = Column(String(64), nullable=True)  # SHA-256 of generated file content
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    order = relationship("Order", back_populates="export_records", foreign_keys=[order_id])
    export_profile = relationship("ExportProfile", foreign_keys=[export_profile_id])
