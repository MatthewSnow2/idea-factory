"""User API endpoints for Idea Factory.

Handles user profile, terms acceptance, and user-scoped operations.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..auth.middleware import get_current_user, require_admin
from ..core.models import AcceptTermsInput, User, UserResponse
from ..db.repository import repository

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    user: Annotated[User, Depends(get_current_user)]
) -> UserResponse:
    """Get current user's profile.

    Returns user info and whether terms acceptance is needed.
    """
    return UserResponse(
        user=user,
        needs_terms_acceptance=user.terms_accepted_at is None,
    )


@router.post("/accept-terms", response_model=UserResponse)
async def accept_terms(
    user: Annotated[User, Depends(get_current_user)],
    input_data: AcceptTermsInput,
) -> UserResponse:
    """Accept terms of use.

    Must be called before accessing protected resources.
    """
    if user.terms_accepted_at:
        # Already accepted
        return UserResponse(
            user=user,
            needs_terms_acceptance=False,
        )

    updated_user = await repository.accept_terms(user.id)
    if not updated_user:
        raise HTTPException(status_code=500, detail="Failed to update user")

    return UserResponse(
        user=updated_user,
        needs_terms_acceptance=False,
    )


@router.get("/terms", response_model=dict)
async def get_terms() -> dict:
    """Get terms of use content.

    Returns the terms that users must accept.
    """
    return {
        "version": "1.0",
        "content": """
# Idea Factory Terms of Use

By using Idea Factory, you acknowledge and agree to the following:

## Privacy & Data

- This system is operated by Matthew on personal infrastructure
- Your ideas may be visible to the system owner and collaborators
- Completed projects are stored in a shared Google Drive folder
- No expectation of confidentiality for submitted content

## Security

- Your authentication credentials remain secure (handled by Netlify Identity)
- We do not store or have access to your Google account password

## Usage

- Use this service for legitimate project ideation and development
- Do not submit illegal, harmful, or offensive content
- Rate limits may apply (10 ideas per day per user)

## Liability

- This is a personal project with no warranty or guarantee
- We are not responsible for any outcomes from using generated projects
- Use at your own risk

By clicking "Accept", you confirm you have read and agree to these terms.
""",
        "last_updated": "2025-01-17",
    }


@router.get("", response_model=list[User])
async def list_users(
    _admin: Annotated[User, Depends(require_admin)],
    limit: int = 100,
    offset: int = 0,
) -> list[User]:
    """List all users (admin only)."""
    return await repository.list_users(limit=limit, offset=offset)
