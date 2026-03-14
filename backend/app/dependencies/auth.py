# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-23 21:30 UTC
# Authentication dependencies

"""
Authentication Dependencies
===========================
FastAPI dependency functions for authentication validation.
"""

import hashlib
from datetime import datetime, timezone
from http.cookies import SimpleCookie

from fastapi import Depends, HTTPException, status, Request

from app.core.auth import verify_password, parse_basic_auth, verify_basic_auth_plaintext
from app.dependencies import state


SESSION_COOKIE_NAME = "ham_auth_session"


def _verify_credentials(user: str, password: str) -> bool:
    if not user or not password or user != state.auth_user:
        return False
    if state.auth_pass_is_hashed:
        return verify_password(password, state.auth_pass)
    return password == state.auth_pass


def _parse_cookie_header(cookie_header: str) -> dict:
    if not cookie_header:
        return {}
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    return {key: morsel.value for key, morsel in cookie.items()}


def verify_session_token(session_token: str) -> bool:
    if not session_token:
        return False
    session = state.db.get_auth_session()
    if not session.get("session_hash") or not session.get("expires_at"):
        return False
    try:
        expires_at = datetime.fromisoformat(session["expires_at"])
    except ValueError:
        state.db.clear_auth_session()
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        state.db.clear_auth_session()
        return False
    session_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
    return session_hash == session.get("session_hash")


def verify_session_cookie_header(cookie_header: str) -> bool:
    cookies = _parse_cookie_header(cookie_header)
    return verify_session_token(cookies.get(SESSION_COOKIE_NAME, ""))


def get_authenticated_user(request: Request) -> str | None:
    if not state.auth_required:
        return None
    session_token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if verify_session_token(session_token):
        return state.db.get_auth_session().get("user") or state.auth_user
    authorization = request.headers.get("authorization", "")
    credentials = parse_basic_auth(authorization)
    if not credentials:
        return None
    user, password = credentials
    if _verify_credentials(user, password):
        return user
    return None


def verify_basic_auth(request: Request) -> None:
    """
    FastAPI dependency to verify Basic Authentication.
    
    Supports both plaintext and bcrypt-hashed passwords.
    Raises HTTPException if authentication fails.
    
    Args:
        request: FastAPI Request object
        
    Raises:
        HTTPException: 401 if auth fails, 403 if credentials invalid
    """
    # If auth is not required (AUTH_REQUIRED=0 or no credentials configured), allow access
    if not state.auth_required:
        return

    if get_authenticated_user(request):
        return
    
    # Get Authorization header
    authorization = request.headers.get("authorization", "")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    
    # Parse credentials
    user, password = parse_basic_auth(authorization)
    if not user or not password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
        )
    
    # Verify username
    if user != state.auth_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid credentials",
        )
    
    # Verify password (bcrypt or plaintext)
    if state.auth_pass_is_hashed:
        # Use bcrypt verification
        if not verify_password(password, state.auth_pass):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid credentials",
            )
    else:
        # Use plaintext comparison (legacy)
        if password != state.auth_pass:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid credentials",
            )


def optional_verify_basic_auth(request: Request) -> bool:
    """
    Optional authentication dependency that returns True if authenticated.
    
    Useful for endpoints that have different behavior for authenticated users
    but don't require authentication.
    
    Args:
        request: FastAPI Request object
        
    Returns:
        bool: True if authenticated, False otherwise
    """
    # If no auth configured, return False
    if not state.auth_user or not state.auth_pass:
        return False

    if get_authenticated_user(request):
        return True
    
    # Get Authorization header
    authorization = request.headers.get("authorization", "")
    if not authorization:
        return False
    
    # Parse credentials
    user, password = parse_basic_auth(authorization)
    if not user or not password:
        return False
    
    # Verify username
    if user != state.auth_user:
        return False
    
    # Verify password (bcrypt or plaintext)
    if state.auth_pass_is_hashed:
        return verify_password(password, state.auth_pass)
    else:
        return password == state.auth_pass
