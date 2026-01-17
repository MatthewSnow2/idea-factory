"""Status and health check API routes."""

import logging
import os
from datetime import datetime

from fastapi import APIRouter

from ..db.repository import repository

logger = logging.getLogger(__name__)
router = APIRouter(tags=["status"])


async def _check_database() -> dict:
    """Check database connectivity."""
    try:
        # Simple query to verify connection
        await repository.get_stage_counts()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {"status": "error", "message": str(e)}


def _check_anthropic() -> dict:
    """Check Anthropic API configuration."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"status": "configured"}
    return {"status": "not_configured"}


def _check_google_drive() -> dict:
    """Check Google Drive configuration."""
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")

    if creds_path and os.path.exists(creds_path) and folder_id:
        return {"status": "configured"}
    elif creds_path or folder_id:
        return {"status": "partially_configured"}
    return {"status": "not_configured"}


def _check_netlify() -> dict:
    """Check Netlify Identity configuration."""
    if os.environ.get("NETLIFY_SITE_URL"):
        return {"status": "configured"}
    return {"status": "not_configured"}


@router.get("/health")
async def health_check() -> dict:
    """Health check endpoint with component status."""
    db_status = await _check_database()

    # Overall status is "ok" if database is working
    overall_status = "ok" if db_status["status"] == "ok" else "degraded"

    return {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat(),
        "service": "agentic-idea-factory",
        "version": "0.2.0",
        "components": {
            "database": db_status,
            "anthropic_api": _check_anthropic(),
            "google_drive": _check_google_drive(),
            "netlify_identity": _check_netlify(),
        },
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
