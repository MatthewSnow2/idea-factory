"""FastAPI authentication middleware.

Provides dependencies for protecting routes with Netlify Identity JWTs.
"""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..core.models import User
from ..db.repository import repository
from .netlify_jwt import NetlifyJWTError, extract_user_info, verify_netlify_token

logger = logging.getLogger(__name__)

# HTTP Bearer scheme for JWT tokens
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
) -> User:
    """Dependency to get the current authenticated user.

    Validates the JWT token from Authorization header and returns the user.
    Creates user record if first login.

    Raises:
        HTTPException 401: If no token provided or token is invalid
        HTTPException 403: If user hasn't accepted terms (for certain endpoints)
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # Verify the token via Netlify Identity
        user_data = await verify_netlify_token(credentials.credentials)
        user_info = extract_user_info(user_data)

        # Get or create user in database
        user = await repository.get_user(user_info["id"])

        if not user:
            # First login - create user record
            logger.info(f"Creating new user: {user_info['email']}")
            user = await repository.create_user(
                user_id=user_info["id"],
                email=user_info["email"],
                name=user_info["name"],
                role=user_info["role"],
            )
        else:
            # Update user info if changed (name, role from Netlify)
            if user.email != user_info["email"] or user.name != user_info["name"]:
                user = await repository.update_user(
                    user_id=user_info["id"],
                    email=user_info["email"],
                    name=user_info["name"],
                )

        return user

    except NetlifyJWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
) -> User | None:
    """Dependency to get current user if authenticated, None otherwise.

    Useful for endpoints that work both authenticated and unauthenticated.
    """
    if not credentials:
        return None

    try:
        user_data = await verify_netlify_token(credentials.credentials)
        user_info = extract_user_info(user_data)
        return await repository.get_user(user_info["id"])
    except NetlifyJWTError:
        return None


async def require_terms_accepted(
    user: Annotated[User, Depends(get_current_user)]
) -> User:
    """Dependency that requires user to have accepted terms.

    Use this for endpoints that require terms acceptance.
    """
    if not user.terms_accepted_at:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must accept the terms of use before accessing this resource",
        )
    return user


async def require_admin(
    user: Annotated[User, Depends(get_current_user)]
) -> User:
    """Dependency that requires admin role.

    Use this for admin-only endpoints.
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
