# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Logs API endpoint

"""
Logs API
========
Application logs retrieval endpoint.
"""

from typing import List

from fastapi import APIRouter, Depends

from app.dependencies import state
from app.dependencies.auth import optional_verify_basic_auth


router = APIRouter(prefix="/api", tags=["logs"])


@router.get("/logs")
def logs(limit: int = 200, _: bool = Depends(optional_verify_basic_auth)) -> List[str]:
    """
    Get application logs.
    
    Returns recent log entries. Authentication is optional for this endpoint.
    
    Args:
        limit: Maximum number of log entries to return (default: 200)
        
    Returns:
        List of log entry strings
    """
    return state.logs[-limit:]
