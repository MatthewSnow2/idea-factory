"""Netlify Identity JWT verification.

Validates JWTs by calling Netlify Identity's user endpoint.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)


class NetlifyJWTError(Exception):
    """Error verifying Netlify JWT."""
    pass


async def verify_netlify_token(token: str) -> dict:
    """Verify a Netlify Identity JWT by calling the user endpoint.

    Args:
        token: The JWT access token from Netlify Identity

    Returns:
        Dict with user data from Netlify Identity

    Raises:
        NetlifyJWTError: If token is invalid or verification fails
    """
    site_url = os.environ.get("NETLIFY_SITE_URL", "")
    if not site_url:
        raise NetlifyJWTError("NETLIFY_SITE_URL environment variable not set")

    # Remove trailing slash
    site_url = site_url.rstrip("/")
    user_url = f"{site_url}/.netlify/identity/user"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                user_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )

            if response.status_code == 401:
                error_data = response.json()
                raise NetlifyJWTError(f"Invalid token: {error_data.get('msg', 'Unauthorized')}")

            if response.status_code != 200:
                raise NetlifyJWTError(f"Netlify Identity error: HTTP {response.status_code}")

            return response.json()

    except httpx.RequestError as e:
        logger.error(f"Request to Netlify Identity failed: {e}")
        raise NetlifyJWTError(f"Failed to verify token: {e}")
    except Exception as e:
        if isinstance(e, NetlifyJWTError):
            raise
        logger.error(f"JWT verification error: {e}")
        raise NetlifyJWTError(f"Token verification failed: {e}")


def extract_user_info(user_data: dict) -> dict:
    """Extract user info from Netlify Identity user data.

    Args:
        user_data: User data from Netlify Identity /user endpoint

    Returns:
        Dict with normalized user info:
        - id: User ID
        - email: User email
        - name: User's full name (if available)
        - role: User role from app_metadata (default: 'collaborator')
    """
    user_metadata = user_data.get("user_metadata", {})
    app_metadata = user_data.get("app_metadata", {})

    return {
        "id": user_data.get("id", ""),
        "email": user_data.get("email", ""),
        "name": user_metadata.get("full_name") or user_metadata.get("name", ""),
        "role": app_metadata.get("role", "collaborator"),
    }
