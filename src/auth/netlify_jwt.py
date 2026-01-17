"""Netlify Identity JWT verification.

Validates JWTs issued by Netlify Identity using JWKS.
"""

import logging
import os
from functools import lru_cache

import httpx
import jwt
from jwt import PyJWKClient

logger = logging.getLogger(__name__)


class NetlifyJWTError(Exception):
    """Error verifying Netlify JWT."""
    pass


@lru_cache(maxsize=1)
def get_jwks_client() -> PyJWKClient:
    """Get cached JWKS client for Netlify Identity.

    Netlify Identity uses a standard JWKS endpoint at:
    https://<site>.netlify.app/.netlify/identity/.well-known/jwks.json
    """
    site_url = os.environ.get("NETLIFY_SITE_URL", "")
    if not site_url:
        raise NetlifyJWTError("NETLIFY_SITE_URL environment variable not set")

    # Remove trailing slash
    site_url = site_url.rstrip("/")
    jwks_url = f"{site_url}/.netlify/identity/.well-known/jwks.json"

    logger.info(f"Initializing JWKS client with URL: {jwks_url}")
    return PyJWKClient(jwks_url)


def verify_netlify_token(token: str) -> dict:
    """Verify a Netlify Identity JWT and return claims.

    Args:
        token: The JWT access token from Netlify Identity

    Returns:
        Dict with decoded token claims including:
        - sub: User ID
        - email: User email
        - app_metadata: App-level metadata
        - user_metadata: User-level metadata

    Raises:
        NetlifyJWTError: If token is invalid or verification fails
    """
    site_url = os.environ.get("NETLIFY_SITE_URL", "")
    if not site_url:
        raise NetlifyJWTError("NETLIFY_SITE_URL environment variable not set")

    try:
        # Get the signing key from JWKS
        jwks_client = get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Verify and decode the token
        # Netlify Identity tokens use RS256 and the site URL as audience
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=site_url.rstrip("/"),
            options={
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": False,  # Netlify doesn't always set issuer consistently
            }
        )

        return claims

    except jwt.ExpiredSignatureError:
        raise NetlifyJWTError("Token has expired")
    except jwt.InvalidAudienceError:
        raise NetlifyJWTError("Invalid token audience")
    except jwt.InvalidTokenError as e:
        raise NetlifyJWTError(f"Invalid token: {e}")
    except Exception as e:
        logger.error(f"JWT verification error: {e}")
        raise NetlifyJWTError(f"Token verification failed: {e}")


def extract_user_info(claims: dict) -> dict:
    """Extract user info from JWT claims.

    Args:
        claims: Decoded JWT claims

    Returns:
        Dict with normalized user info:
        - id: User ID (sub claim)
        - email: User email
        - name: User's full name (if available)
        - role: User role from app_metadata (default: 'collaborator')
    """
    user_metadata = claims.get("user_metadata", {})
    app_metadata = claims.get("app_metadata", {})

    return {
        "id": claims["sub"],
        "email": claims.get("email", ""),
        "name": user_metadata.get("full_name") or user_metadata.get("name", ""),
        "role": app_metadata.get("role", "collaborator"),
    }
