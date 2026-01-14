"""FastAPI entry point for Agentic Idea Factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import ideas, reviews, status
from .db.repository import repository

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Agentic Idea Factory...")
    await repository.connect()
    logger.info("Database connected")
    yield
    # Shutdown
    logger.info("Shutting down...")
    await repository.close()
    logger.info("Database disconnected")


app = FastAPI(
    title="Agentic Idea Factory",
    description="Python-orchestrated idea pipeline with MCP persona agents",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(status.router)
app.include_router(ideas.router)
app.include_router(reviews.router)


@app.get("/")
async def root() -> dict:
    """Root endpoint with API overview."""
    return {
        "service": "Agentic Idea Factory",
        "version": "0.1.0",
        "description": "Python-orchestrated idea pipeline with MCP persona agents",
        "endpoints": {
            "health": "GET /health",
            "stats": "GET /api/stats",
            "ideas": {
                "list": "GET /api/ideas",
                "create": "POST /api/ideas",
                "get": "GET /api/ideas/{id}",
                "status": "GET /api/ideas/{id}/status",
                "start": "POST /api/ideas/{id}/start",
                "continue": "POST /api/ideas/{id}/continue",
                "analyze": "POST /api/ideas/{id}/analyze",
            },
            "reviews": {
                "submit": "POST /api/reviews/{id}",
                "get": "GET /api/reviews/{id}",
                "pending": "GET /api/reviews/pending/count",
            },
        },
        "pipeline_stages": [
            "INPUT → ENRICHMENT → EVALUATION → HUMAN_REVIEW → SCAFFOLDING → BUILDING → COMPLETED"
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
