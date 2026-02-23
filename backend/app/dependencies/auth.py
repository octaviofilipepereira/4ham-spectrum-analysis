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

from fastapi import Depends, HTTPException, status, Request

from app.core.auth import verify_password, parse_basic_auth, verify_basic_auth_plaintext
from app.dependencies import state


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
    
    # Get Authorization header
    authorization = request.headers.get("authorization", "")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Basic realm=\"4ham Spectrum Analysis\""},
        )
    
    # Parse credentials
    user, password = parse_basic_auth(authorization)
    if not user or not password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
            headers={"WWW-Authenticate": "Basic realm=\"4ham Spectrum Analysis\""},
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
