# Copyright 2026 Lazaros Avramidis (alexneverland)
# SPDX-License-Identifier: Apache-2.0

from contextlib import asynccontextmanager
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Request
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
    allow_origins=["http://127.0.0.1:5173"] if settings.APP_ENV == "development" else [],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def local_browser_boundary(request: Request, call_next):
    # Host validation prevents DNS rebinding. Origin checks must reject the
    # request itself: CORS alone only controls whether browsers can read it.
    host = request.headers.get("host", "")
    try:
        hostname = urlsplit(f"http://{host}").hostname
    except ValueError:
        hostname = None
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        return JSONResponse(status_code=403, content={"detail": "OrderMind requires a localhost Host"})
    allowed_origins = {f"{request.url.scheme}://{host}"}
    if settings.APP_ENV == "development":
        allowed_origins.add("http://127.0.0.1:5173")
    origin = request.headers.get("origin")
    if origin is not None and origin not in allowed_origins:
        return JSONResponse(status_code=403, content={"detail": "OrderMind requires a trusted local origin"})
    if origin is None and request.headers.get("sec-fetch-site") == "cross-site":
        return JSONResponse(status_code=403, content={"detail": "Cross-site browser requests are not allowed"})
    return await call_next(request)


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
