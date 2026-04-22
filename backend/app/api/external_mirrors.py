# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""
External Mirrors Admin REST API.

All endpoints require Basic Auth via :func:`verify_basic_auth`.
Plaintext tokens are returned ONCE on create / rotate-token; never
stored or returned afterwards.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status

from app.dependencies.auth import verify_basic_auth
from app.external_mirrors import (
    ExternalMirror,
    MirrorNameConflictError,
    MirrorNotFoundError,
)
from app.external_mirrors import registry as mirrors_registry
from app.external_mirrors.http_client import MirrorHttpClient


router = APIRouter()


def _serialise(mirror: ExternalMirror) -> Dict[str, Any]:
    return mirror.to_public_dict()


def _ensure_initialised() -> None:
    if not mirrors_registry.is_initialised():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External mirrors subsystem not initialised",
        )


@router.get("")
def list_mirrors(
    include_disabled: bool = Query(True),
    _: None = Depends(verify_basic_auth),
) -> Dict[str, Any]:
    _ensure_initialised()
    repo = mirrors_registry.get_repository()
    mirrors = repo.list(include_disabled=include_disabled)
    return {"mirrors": [_serialise(m) for m in mirrors]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_mirror(
    payload: Dict[str, Any] = Body(...),
    _: None = Depends(verify_basic_auth),
) -> Dict[str, Any]:
    _ensure_initialised()
    repo = mirrors_registry.get_repository()
    cache = mirrors_registry.get_token_cache()

    name = (payload.get("name") or "").strip()
    endpoint_url = (payload.get("endpoint_url") or "").strip()
    if not name or not endpoint_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="name and endpoint_url are required",
        )

    try:
        result = repo.create(
            name=name,
            endpoint_url=endpoint_url,
            created_by=payload.get("created_by") or "admin",
            push_interval_seconds=int(payload.get("push_interval_seconds", 300)),
            data_scopes=payload.get("data_scopes") or [],
            retention_days=payload.get("retention_days"),
            enabled=bool(payload.get("enabled", True)),
        )
    except MirrorNameConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    cache.set(result.mirror.id, result.plaintext_token)
    return {
        "mirror": _serialise(result.mirror),
        "plaintext_token": result.plaintext_token,  # shown ONCE.
    }


@router.get("/{mirror_id}")
def get_mirror(
    mirror_id: int = Path(..., ge=1),
    _: None = Depends(verify_basic_auth),
) -> Dict[str, Any]:
    _ensure_initialised()
    repo = mirrors_registry.get_repository()
    mirror = repo.get(mirror_id)
    if mirror is None:
        raise HTTPException(status_code=404, detail="mirror not found")
    return {"mirror": _serialise(mirror)}


@router.patch("/{mirror_id}")
def update_mirror(
    payload: Dict[str, Any] = Body(...),
    mirror_id: int = Path(..., ge=1),
    _: None = Depends(verify_basic_auth),
) -> Dict[str, Any]:
    _ensure_initialised()
    repo = mirrors_registry.get_repository()
    fields = {k: v for k, v in payload.items() if k != "actor"}
    actor = payload.get("actor") or "admin"
    try:
        updated = repo.update(mirror_id, actor=actor, **fields)
    except MirrorNotFoundError:
        raise HTTPException(status_code=404, detail="mirror not found") from None
    except MirrorNameConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"mirror": _serialise(updated)}


@router.delete("/{mirror_id}")
def delete_mirror(
    mirror_id: int = Path(..., ge=1),
    _: None = Depends(verify_basic_auth),
) -> Dict[str, Any]:
    _ensure_initialised()
    repo = mirrors_registry.get_repository()
    cache = mirrors_registry.get_token_cache()
    deleted = repo.delete(mirror_id, actor="admin")
    if not deleted:
        raise HTTPException(status_code=404, detail="mirror not found")
    cache.drop(mirror_id)
    return {"deleted": True, "id": mirror_id}


@router.post("/{mirror_id}/enable")
def enable_mirror(
    mirror_id: int = Path(..., ge=1),
    _: None = Depends(verify_basic_auth),
) -> Dict[str, Any]:
    _ensure_initialised()
    repo = mirrors_registry.get_repository()
    try:
        updated = repo.set_enabled(mirror_id, True, actor="admin")
    except MirrorNotFoundError:
        raise HTTPException(status_code=404, detail="mirror not found") from None
    return {"mirror": _serialise(updated)}


@router.post("/{mirror_id}/disable")
def disable_mirror(
    mirror_id: int = Path(..., ge=1),
    _: None = Depends(verify_basic_auth),
) -> Dict[str, Any]:
    _ensure_initialised()
    repo = mirrors_registry.get_repository()
    try:
        updated = repo.set_enabled(mirror_id, False, actor="admin")
    except MirrorNotFoundError:
        raise HTTPException(status_code=404, detail="mirror not found") from None
    return {"mirror": _serialise(updated)}


@router.post("/{mirror_id}/rotate-token")
def rotate_mirror_token(
    mirror_id: int = Path(..., ge=1),
    _: None = Depends(verify_basic_auth),
) -> Dict[str, Any]:
    _ensure_initialised()
    repo = mirrors_registry.get_repository()
    cache = mirrors_registry.get_token_cache()
    try:
        result = repo.rotate_token(mirror_id, actor="admin")
    except MirrorNotFoundError:
        raise HTTPException(status_code=404, detail="mirror not found") from None
    cache.set(mirror_id, result.plaintext_token)
    return {
        "mirror": _serialise(result.mirror),
        "plaintext_token": result.plaintext_token,
    }


@router.get("/{mirror_id}/audit")
def get_mirror_audit(
    mirror_id: int = Path(..., ge=1),
    limit: int = Query(100, ge=1, le=1000),
    _: None = Depends(verify_basic_auth),
) -> Dict[str, Any]:
    _ensure_initialised()
    repo = mirrors_registry.get_repository()
    if repo.get(mirror_id) is None:
        raise HTTPException(status_code=404, detail="mirror not found")
    return {"audit": repo.list_audit(mirror_id, limit=limit)}


@router.post("/{mirror_id}/test")
def test_mirror(
    mirror_id: int = Path(..., ge=1),
    _: None = Depends(verify_basic_auth),
) -> Dict[str, Any]:
    """
    Send a one-shot test ping to the mirror's endpoint with a small probe
    payload. Result does NOT update the watermark or consecutive_failures.
    """
    _ensure_initialised()
    repo = mirrors_registry.get_repository()
    cache = mirrors_registry.get_token_cache()
    mirror = repo.get(mirror_id)
    if mirror is None:
        raise HTTPException(status_code=404, detail="mirror not found")
    token = cache.get(mirror_id)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No cached token for this mirror — rotate-token first.",
        )

    probe_payload: Dict[str, Any] = {
        "meta": {"test": True, "mirror_name": mirror.name},
        "events": {"callsign": [], "occupancy": []},
        "counts": {"callsign": 0, "occupancy": 0},
    }
    client = MirrorHttpClient()
    result = client.post(
        mirror.endpoint_url,
        probe_payload,
        secret_token=token,
        mirror_name=mirror.name,
    )
    repo.log_event(
        mirror_id,
        "test_push",
        actor="admin",
        details={
            "success": result.success,
            "status_code": result.status_code,
            "attempts": result.attempts,
            "error": result.error,
            "elapsed_ms": result.elapsed_ms,
        },
    )
    return {
        "success": result.success,
        "status_code": result.status_code,
        "attempts": result.attempts,
        "error": result.error,
        "elapsed_ms": result.elapsed_ms,
        "response_body": result.response_body,
    }
