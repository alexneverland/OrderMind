from fastapi import APIRouter
from backend.app.api.v1.companies import router as companies_router
from backend.app.api.v1.customers import router as customers_router
from backend.app.api.v1.products import router as products_router
from backend.app.api.v1.imports import router as imports_router
from backend.app.api.v1.orders import router as orders_router
from backend.app.api.v1.export_profiles import router as export_profiles_router
from backend.app.api.v1.runtime_settings import router as runtime_settings_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(companies_router)
api_router.include_router(customers_router)
api_router.include_router(products_router)
api_router.include_router(imports_router)
api_router.include_router(orders_router)
api_router.include_router(export_profiles_router)
api_router.include_router(runtime_settings_router)
