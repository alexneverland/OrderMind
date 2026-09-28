from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_code = Column(String(100), nullable=False, index=True)
    customer_name = Column(String(255), nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(100), nullable=True, index=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "customer_code", name="uq_company_customer_code"),
        UniqueConstraint("id", "company_id", name="uq_customers_id_company_id"),
    )

    # Relationships
    company = relationship("Company", back_populates="customers")
    contacts = relationship("CustomerContact", back_populates="customer", cascade="all, delete-orphan")
    aliases = relationship("CustomerProductAlias", back_populates="customer", cascade="all, delete-orphan", foreign_keys="CustomerProductAlias.customer_id")
    orders = relationship(
        "Order",
        back_populates="customer",
        primaryjoin="and_(Customer.id==Order.customer_id, Customer.company_id==Order.company_id)",
        overlaps="company,orders"
    )
    corrections = relationship("HumanCorrection", back_populates="customer", cascade="all, delete-orphan", foreign_keys="HumanCorrection.customer_id")


class CustomerContact(Base):
    __tablename__ = "customer_contacts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(100), nullable=True)
    role = Column(String(100), nullable=True)

    # Relationships
    customer = relationship("Customer", back_populates="contacts")
