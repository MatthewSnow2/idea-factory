"""FastAPI entry point for Agentic Idea Factory."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables: shared first, then local overrides
shared_env = Path.home() / ".env.shared"
if shared_env.exists():
    load_dotenv(shared_env)
load_dotenv()  # Local .env can override

from .api import chat, ideas, reviews, status, users
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

# CORS middleware - configured for Netlify dashboard
CORS_ORIGINS = [
    "https://idea-factory.netlify.app",
    "https://idea-factory-dashboard.netlify.app",
    "http://localhost:3000",  # Local development
    "http://localhost:5173",  # Vite dev server
]

# Allow all origins in development
if os.environ.get("ENVIRONMENT", "development") == "development":
    CORS_ORIGINS = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(status.router)
app.include_router(ideas.router)
app.include_router(reviews.router)
app.include_router(users.router)
app.include_router(chat.router)


@app.get("/")
async def root() -> dict:
    """Root endpoint with API overview."""
    return {
        "service": "Agentic Idea Factory",
        "version": "0.2.0",
        "description": "Python-orchestrated idea pipeline with MCP persona agents",
        "endpoints": {
            "health": "GET /health",
            "stats": "GET /api/stats",
            "users": {
                "me": "GET /api/users/me",
                "accept_terms": "POST /api/users/accept-terms",
                "terms": "GET /api/users/terms",
                "list": "GET /api/users (admin)",
            },
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
            "chat": {
                "vetting": "POST /api/chat/vetting",
                "get_conversation": "GET /api/chat/vetting/{id}",
                "delete_conversation": "DELETE /api/chat/vetting/{id}",
            },
        },
        "pipeline_stages": [
            "INPUT → ENRICHMENT → EVALUATION → HUMAN_REVIEW → SCAFFOLDING → BUILDING → COMPLETED"
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
