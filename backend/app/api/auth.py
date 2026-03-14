# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Auth status and credential management endpoints

"""
Auth API
========
Public auth-status endpoint and credential management endpoint.
"""

import os
from typing import Dict

from fastapi import APIRouter, HTTPException, Request, status

from app.dependencies import state
from app.dependencies.auth import verify_basic_auth
from app.core.auth import hash_password, parse_basic_auth, verify_password

router = APIRouter()


@router.get("/status")
def auth_status() -> Dict:
    """
    Return whether the server currently requires authentication.

    This endpoint is always public (no auth required) so the frontend can
    decide whether to show the login form before making any other request.
    """
    _env_user = os.getenv("BASIC_AUTH_USER")
    source: str
    if state.auth_required:
        db_cfg = state.db.get_auth_config()
        source = "db" if (db_cfg.get("auth_user") and db_cfg.get("auth_pass_hash")) else "env"
    else:
        source = "none"

    return {
        "auth_required": bool(state.auth_required),
        "source": source,
        "env_locked": bool(_env_user),  # UI should warn when env vars are controlling auth
    }


@router.post("/credentials")
def set_credentials(payload: dict, request: Request) -> Dict:
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
    if _env_user and _env_pass:
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
        authorization = request.headers.get("authorization", "")
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to change credentials",
                headers={"WWW-Authenticate": "Basic realm=\"4ham Spectrum Analysis\""},
            )
        parsed = parse_basic_auth(authorization)
        if not parsed:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Authorization header",
                headers={"WWW-Authenticate": "Basic realm=\"4ham Spectrum Analysis\""},
            )
        req_user, req_pass = parsed
        if req_user != state.auth_user:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid credentials")
        if state.auth_pass_is_hashed:
            ok = verify_password(req_pass, state.auth_pass)
        else:
            ok = req_pass == state.auth_pass
        if not ok:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid credentials")

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
        return {"status": "ok", "auth_required": True, "message": "Credentials saved"}

    # Empty user or password → clear credentials
    state.db.save_auth_config("", "")
    state.reload_auth_from_db()
    return {"status": "ok", "auth_required": False, "message": "Credentials cleared"}
