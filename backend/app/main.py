from contextlib import asynccontextmanager
import sqlite3
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError

from backend.app.config import settings
from backend.app.core.database import enable_sqlite_wal
from backend.app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    enable_sqlite_wal()
    yield


app = FastAPI(
    title="OrderMind API",
    description="Intelligent Multi-Channel B2B Order Intake, Normalization & Matching Platform",
    version="0.1.0",
    lifespan=lifespan,
    debug=settings.APP_DEBUG
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router)

# Serve a built operator workspace from the same origin as the API.
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (frontend_dist / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    @app.get("/orders", include_in_schema=False)
    @app.get("/orders/new", include_in_schema=False)
    @app.get("/orders/{order_id}", include_in_schema=False)
    @app.get("/customers", include_in_schema=False)
    @app.get("/products", include_in_schema=False)
    @app.get("/export-profiles", include_in_schema=False)
    @app.get("/settings", include_in_schema=False)
    def operator_workspace(order_id: str | None = None):
        return FileResponse(frontend_dist / "index.html")


@app.exception_handler(OperationalError)
async def sqlite_operational_error_handler(request, exc: OperationalError):
    code = getattr(exc.orig, "sqlite_errorcode", None)
    if code is not None and code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return JSONResponse(
            status_code=503,
            content={"detail": "Database is busy; retry shortly"},
            headers={"Retry-After": "1"},
        )
    return JSONResponse(status_code=500, content={"detail": "Database operation failed"})


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "service": "OrderMind",
        "env": settings.APP_ENV,
        "database": settings.DATABASE_URL.split("://")[0]
    }
