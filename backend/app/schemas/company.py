from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional


class CompanyBase(BaseModel):
    name: str
    tax_id: Optional[str] = None


class CompanyCreate(CompanyBase):
    pass


class CompanyResponse(CompanyBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
