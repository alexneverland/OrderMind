from sqlalchemy import Column, Integer, String, DateTime, func
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    tax_id = Column(String(50), nullable=True)  # AFM
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    customers = relationship("Customer", back_populates="company", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="company", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="company", cascade="all, delete-orphan")
    export_profiles = relationship("ExportProfile", back_populates="company", cascade="all, delete-orphan")
    global_aliases = relationship("ProductAlias", back_populates="company", cascade="all, delete-orphan")
