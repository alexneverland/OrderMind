from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import settings
from backend.app.core.database import init_db
from backend.app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup
    init_db()
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


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "service": "OrderMind",
        "env": settings.APP_ENV,
        "database": settings.DATABASE_URL.split("://")[0]
    }
