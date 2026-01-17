"""Rate limiting for Idea Factory.

Simple in-memory rate limiting for idea submissions.
For production, consider Redis-based rate limiting.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status

from ..core.models import User
from .middleware import get_current_user

logger = logging.getLogger(__name__)

# In-memory rate limit storage
# Format: {user_id: [timestamp1, timestamp2, ...]}
_rate_limits: dict[str, list[datetime]] = defaultdict(list)

# Configuration
RATE_LIMIT_IDEAS_PER_DAY = 10
RATE_LIMIT_WINDOW = timedelta(days=1)


def _cleanup_old_entries(user_id: str) -> None:
    """Remove entries older than the rate limit window."""
    cutoff = datetime.utcnow() - RATE_LIMIT_WINDOW
    _rate_limits[user_id] = [
        ts for ts in _rate_limits[user_id] if ts > cutoff
    ]


def check_rate_limit(user_id: str) -> tuple[bool, int]:
    """Check if user is within rate limit.

    Args:
        user_id: The user's ID

    Returns:
        Tuple of (allowed: bool, remaining: int)
    """
    _cleanup_old_entries(user_id)
    count = len(_rate_limits[user_id])
    remaining = max(0, RATE_LIMIT_IDEAS_PER_DAY - count)
    return count < RATE_LIMIT_IDEAS_PER_DAY, remaining


def record_idea_submission(user_id: str) -> None:
    """Record an idea submission for rate limiting."""
    _rate_limits[user_id].append(datetime.utcnow())


async def require_rate_limit(
    user: Annotated[User, Depends(get_current_user)]
) -> User:
    """Dependency that enforces rate limiting for idea submissions.

    Raises:
        HTTPException 429: If rate limit exceeded
    """
    allowed, remaining = check_rate_limit(user.id)

    if not allowed:
        logger.warning(f"Rate limit exceeded for user: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. You can submit up to {RATE_LIMIT_IDEAS_PER_DAY} ideas per day.",
            headers={"Retry-After": "86400"},  # 24 hours
        )

    return user


def get_rate_limit_status(user_id: str) -> dict:
    """Get rate limit status for a user."""
    _cleanup_old_entries(user_id)
    count = len(_rate_limits[user_id])
    remaining = max(0, RATE_LIMIT_IDEAS_PER_DAY - count)

    # Calculate reset time (oldest entry + window)
    reset_at = None
    if _rate_limits[user_id]:
        oldest = min(_rate_limits[user_id])
        reset_at = (oldest + RATE_LIMIT_WINDOW).isoformat()

    return {
        "limit": RATE_LIMIT_IDEAS_PER_DAY,
        "remaining": remaining,
        "used": count,
        "reset_at": reset_at,
    }
