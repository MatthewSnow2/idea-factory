"""Status and health check API routes."""

from datetime import datetime

from fastapi import APIRouter

from ..db.repository import repository

router = APIRouter(tags=["status"])


@router.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "agentic-idea-factory",
        "version": "0.1.0",
    }


@router.get("/api/stats")
async def get_stats() -> dict:
    """Get pipeline statistics."""
    stage_counts = await repository.get_stage_counts()

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "ideas_by_stage": stage_counts,
        "total_ideas": sum(stage_counts.values()),
    }
