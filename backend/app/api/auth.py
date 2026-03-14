# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Auth status and credential management endpoints

"""
Auth API
========
Public auth-status endpoint and session-based login/credential management.
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.dependencies import state
from app.dependencies.auth import SESSION_COOKIE_NAME, get_authenticated_user
from app.core.auth import hash_password, parse_basic_auth, verify_password

router = APIRouter()


def _set_session_cookie(response: Response, user: str) -> None:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    state.db.save_auth_session(token_hash, expires_at.isoformat(), user)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=24 * 60 * 60,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    state.db.clear_auth_session()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def _verify_request_credentials(request: Request) -> bool:
    authorization = request.headers.get("authorization", "")
    if not authorization:
        return False
    parsed = parse_basic_auth(authorization)
    if not parsed:
        return False
    req_user, req_pass = parsed
    if req_user != state.auth_user:
        return False
    if state.auth_pass_is_hashed:
        return verify_password(req_pass, state.auth_pass)
    return req_pass == state.auth_pass


@router.get("/status")
def auth_status(request: Request) -> Dict:
    """
    Return whether the server currently requires authentication.

    This endpoint is always public (no auth required) so the frontend can
    decide whether to show the login form before making any other request.
    """
    _env_user = os.getenv("BASIC_AUTH_USER")
    _env_pass = os.getenv("BASIC_AUTH_PASS")
    db_cfg = state.db.get_auth_config()
    source: str
    env_active = bool(
        _env_user and _env_pass and not bool(db_cfg.get("auth_enabled")) and state.auth_required
    )
    if state.auth_required:
        source = "db" if (db_cfg.get("auth_enabled") and db_cfg.get("auth_user") and db_cfg.get("auth_pass_hash")) else "env"
    else:
        source = "none"

    return {
        "auth_required": bool(state.auth_required),
        "source": source,
        "env_locked": env_active,
        "authenticated": bool(get_authenticated_user(request)),
        "user": get_authenticated_user(request),
    }


@router.post("/login")
def auth_login(payload: dict, response: Response) -> Dict:
    if not state.auth_required:
        return {"status": "ok", "auth_required": False, "authenticated": False, "user": None}

    user = (payload.get("user") or "").strip()
    password = (payload.get("password") or "").strip()
    if not user or not password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Username and password are required")
    if user != state.auth_user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid credentials")
    if state.auth_pass_is_hashed:
        ok = verify_password(password, state.auth_pass)
    else:
        ok = password == state.auth_pass
    if not ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid credentials")

    _set_session_cookie(response, user)
    return {"status": "ok", "auth_required": True, "authenticated": True, "user": user}


@router.post("/logout")
def auth_logout(response: Response) -> Dict:
    _clear_session_cookie(response)
    return {"status": "ok", "authenticated": False}


@router.post("/credentials")
def set_credentials(payload: dict, request: Request, response: Response) -> Dict:
    """
    Set or clear authentication credentials stored in the database.

    This endpoint has two access modes:
    - **Bootstrap mode**: when no credentials are configured anywhere
      (neither in the DB nor in env vars), the endpoint is open to anyone
      so the first admin can set a password.
    - **Protected mode**: when credentials already exist, the caller must
      supply valid credentials in the Authorization header.

    Body:
        user (str): New username. Send empty string to clear credentials.
        password (str): New plaintext password to hash. Send empty string to
            clear credentials.

    Returns a confirmation dict on success.
    """
    # Reject if env-var credentials are configured – those take precedence
    # and cannot be overridden from the UI (they are the emergency fallback).
    _env_user = os.getenv("BASIC_AUTH_USER")
    _env_pass = os.getenv("BASIC_AUTH_PASS")
    db_cfg = state.db.get_auth_config()
    env_active = bool(
        _env_user and _env_pass and not bool(db_cfg.get("auth_enabled")) and state.auth_required
    )
    if env_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Credentials are controlled by BASIC_AUTH_USER / BASIC_AUTH_PASS "
                "environment variables and cannot be changed via the API. "
                "Remove those variables to manage credentials through the web UI."
            ),
        )

    # If credentials are already configured, require valid auth to change them.
    if state.auth_required:
        if not (get_authenticated_user(request) or _verify_request_credentials(request)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to change credentials",
            )

    new_user = (payload.get("user") or "").strip()
    new_pass = (payload.get("password") or "").strip()

    if new_user and new_pass:
        # Validate lengths to prevent excessively long bcrypt inputs
        if len(new_user) > 64:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Username must be 64 characters or fewer")
        if len(new_pass) > 72:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Password must be 72 characters or fewer (bcrypt limit)")
        pass_hash = hash_password(new_pass)
        state.db.save_auth_config(new_user, pass_hash)
        state.reload_auth_from_db()
        _set_session_cookie(response, new_user)
        return {"status": "ok", "auth_required": True, "authenticated": True, "user": new_user, "message": "Credentials saved"}

    # Empty user or password → clear credentials
    state.db.save_auth_config("", "")
    state.reload_auth_from_db()
    _clear_session_cookie(response)
    return {"status": "ok", "auth_required": False, "authenticated": False, "user": None, "message": "Credentials cleared"}
