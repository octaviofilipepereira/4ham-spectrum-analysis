# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Exports API endpoints

"""
Exports API
===========
Event data export management endpoints.
"""

import os
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.dependencies import state
from app.dependencies.auth import optional_verify_basic_auth


router = APIRouter(prefix="/api", tags=["exports"])


@router.get("/export")
def export_events(
    limit: int = 1000,
    offset: int = 0,
    band: Optional[str] = None,
    mode: Optional[str] = None,
    callsign: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    format: str = "csv",
    _: bool = Depends(optional_verify_basic_auth)
):
    """
    Legacy export endpoint - redirects to events endpoint.
    
    Provides backward compatibility for older API clients.
    
    Args:
        limit: Maximum events to export
        offset: Pagination offset
        band: Filter by band
        mode: Filter by mode
        callsign: Filter by callsign
        start: Start timestamp
        end: End timestamp
        format: Export format (csv or json)
        
    Returns:
        CSV or JSON response via events endpoint
    """
    # Import here to avoid circular dependency
    from app.api.events import events
    from fastapi import Request
    
    # Create a mock request for the events endpoint
    # This is a workaround for the legacy API
    return events(
        request=None,
        limit=limit,
        offset=offset,
        band=band,
        mode=mode,
        callsign=callsign,
        start=start,
        end=end,
        format=format,
        _=_
    )


@router.post("/exports")
def create_export(payload: dict, _: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """
    Create a new export file.
    
    Queries events from database and creates a downloadable export file.
    
    Args:
        payload: Export configuration dict with keys:
            - format: Export format ('csv' or 'json')
            - limit: Maximum events to export
            - offset: Pagination offset
            - band: Filter by band
            - mode: Filter by mode
            - callsign: Filter by callsign
            - start: Start timestamp
            - end: End timestamp
            
    Returns:
        Export metadata dict with download URL
        
    Raises:
        HTTPException: 400 if format is unsupported
    """
    payload = payload or {}
    format_name = str(payload.get("format", "csv")).lower()
    
    if format_name not in {"csv", "json"}:
        raise HTTPException(status_code=400, detail="Unsupported export format")

    data = state.db.get_events(
        limit=int(payload.get("limit", 1000)),
        offset=int(payload.get("offset", 0)),
        band=payload.get("band"),
        mode=payload.get("mode"),
        callsign=payload.get("callsign"),
        start=payload.get("start"),
        end=payload.get("end"),
    )
    
    item = state.export_manager.create_export(data, format_name=format_name)
    
    return {
        "status": "ok",
        "export": {
            **item,
            "download_url": f"/api/exports/{item['id']}"
        }
    }


@router.get("/exports")
def list_exports(limit: int = 100, _: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """
    List available export files.
    
    Returns list of export files with metadata and download URLs.
    
    Args:
        limit: Maximum exports to return (default: 100)
        
    Returns:
        Dict with 'items' list containing export metadata
    """
    items = state.export_manager.list_exports(limit=limit)
    
    return {
        "items": [
            {
                **item,
                "download_url": f"/api/exports/{item['id']}"
            }
            for item in items
        ]
    }


@router.get("/exports/{export_id}")
def download_export(export_id: str, _: bool = Depends(optional_verify_basic_auth)) -> FileResponse:
    """
    Download an export file.
    
    Args:
        export_id: Export file identifier
        
    Returns:
        File response with CSV or JSON content
        
    Raises:
        HTTPException: 404 if export not found or file missing
    """
    item = state.export_manager.get_export(export_id)
    
    if not item:
        raise HTTPException(status_code=404, detail="Export not found")
    
    path = item.get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Export file missing")
    
    media = "application/json" if item.get("format") == "json" else "text/csv"
    return FileResponse(path, media_type=media, filename=os.path.basename(path))
