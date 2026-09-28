from fastapi import APIRouter
from backend.app.api.v1.companies import router as companies_router
from backend.app.api.v1.customers import router as customers_router
from backend.app.api.v1.products import router as products_router
from backend.app.api.v1.imports import router as imports_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(companies_router)
api_router.include_router(customers_router)
api_router.include_router(products_router)
api_router.include_router(imports_router)
