"""Authentication package for Idea Factory.

Provides JWT validation for Netlify Identity tokens and rate limiting.
"""

from .middleware import get_current_user, get_optional_user, require_admin, require_terms_accepted
from .netlify_jwt import verify_netlify_token
from .rate_limit import check_rate_limit, get_rate_limit_status, require_rate_limit

__all__ = [
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "require_terms_accepted",
    "verify_netlify_token",
    "check_rate_limit",
    "get_rate_limit_status",
    "require_rate_limit",
]
