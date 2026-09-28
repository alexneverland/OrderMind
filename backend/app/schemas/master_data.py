from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List


class CustomerContactBase(BaseModel):
    contact_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None


class CustomerContactCreate(CustomerContactBase):
    pass


class CustomerContactResponse(CustomerContactBase):
    id: int
    customer_id: int

    model_config = ConfigDict(from_attributes=True)


class CustomerBase(BaseModel):
    customer_code: str
    customer_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    active: bool = True


class CustomerCreate(CustomerBase):
    company_id: int


class CustomerResponse(CustomerBase):
    id: int
    company_id: int
    created_at: datetime
    contacts: List[CustomerContactResponse] = []

    model_config = ConfigDict(from_attributes=True)


class PackagingBase(BaseModel):
    package_type: str
    pieces_per_case: float = 1.0
    weight: Optional[float] = None
    unit: str = "piece"
    package_code: Optional[str] = None
    packaging_barcode: Optional[str] = None


class PackagingCreate(PackagingBase):
    product_id: int


class PackagingResponse(PackagingBase):
    id: int
    product_id: int

    model_config = ConfigDict(from_attributes=True)


class ProductAliasBase(BaseModel):
    original_phrase: str
    normalized_phrase: Optional[str] = None
    active: bool = True


class ProductAliasCreate(ProductAliasBase):
    product_id: int
    company_id: int


class ProductAliasResponse(ProductAliasBase):
    id: int
    company_id: int
    product_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductBase(BaseModel):
    sku: str
    description: str
    barcode: Optional[str] = None
    unit: str = "piece"
    active: bool = True


class ProductCreate(ProductBase):
    company_id: int


class ProductResponse(ProductBase):
    id: int
    company_id: int
    created_at: datetime
    packagings: List[PackagingResponse] = []
    global_aliases: List[ProductAliasResponse] = []

    model_config = ConfigDict(from_attributes=True)


class CustomerProductAliasBase(BaseModel):
    original_phrase: str
    normalized_phrase: Optional[str] = None
    confirmed_count: int = 1
    corrected_count: int = 0
    active: bool = True


class CustomerProductAliasCreate(CustomerProductAliasBase):
    customer_id: int
    product_id: int


class CustomerProductAliasResponse(CustomerProductAliasBase):
    id: int
    customer_id: int
    product_id: int
    last_confirmed_at: datetime

    model_config = ConfigDict(from_attributes=True)
