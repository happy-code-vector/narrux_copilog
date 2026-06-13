"""FastAPI application entry point.

Minimal skeleton. Routes from api/routes/.
"""

import structlog
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import get_settings
from retrieval.vector_store import close_client, get_stats, init_client

settings = get_settings()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer()
        if settings.environment == "development"
        else structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    logger.info("starting_aitrate_agent", environment=settings.environment)
    init_client()
    logger.info("qdrant_initialised")
    yield
    close_client()
    logger.info("shutting_down_aitrate_agent")


app = FastAPI(
    title="NARRUX aiTrate Co-Pilot API",
    description="RAG-based trading strategy co-pilot",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow all origins in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include route modules
from api.routes.health import router as health_router
from api.routes.chat import router as chat_router

app.include_router(health_router)
app.include_router(chat_router)


@app.get("/health")
async def health():
    """Root health check endpoint."""
    try:
        stats = await get_stats()
        return {"status": "ok", "kb_stats": stats}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/")
async def serve_frontend():
    """Serve the Co-Pilot frontend."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"error": "Frontend not found"}


# Mount static files if frontend directory exists
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
