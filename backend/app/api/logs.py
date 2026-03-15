# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Logs API endpoint

"""
Logs API
========
Application logs retrieval endpoint.
"""

import os
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends

from app.dependencies import state
from app.dependencies.auth import optional_verify_basic_auth

# Resolve the log file path: env var LOG_FILE overrides default <project_root>/logs/backend.log
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_LOG_FILE = _PROJECT_ROOT / "logs" / "backend.log"
_LOG_FILE_STR = os.getenv("LOG_FILE", str(_DEFAULT_LOG_FILE))
_LOG_FILE = Path(_LOG_FILE_STR).expanduser()

# If LOG_FILE env is relative or invalid, use default
if not _LOG_FILE.is_absolute():
    _LOG_FILE = _DEFAULT_LOG_FILE

router = APIRouter()


@router.get("/logs")
def logs(limit: int = 200, _: bool = Depends(optional_verify_basic_auth)) -> List[str]:
    """
    Get application logs.
    
    Returns recent log entries from the in-memory buffer. Authentication is optional.
    
    Args:
        limit: Maximum number of log entries to return (default: 200)
        
    Returns:
        List of log entry strings
    """
    # state.logs is a deque — convert to list for slicing
    return list(state.logs)[-limit:]


@router.get("/logs/file")
def logs_file(limit: int = 2000, _: bool = Depends(optional_verify_basic_auth)) -> List[str]:
    """
    Get last N lines from the backend log file (logs/backend.log).
    
    Args:
        limit: Maximum number of lines to return (default: 2000)
        
    Returns:
        List of log lines, or empty list if the file does not exist.
    """
    if not _LOG_FILE.exists():
        return []
    try:
        with open(_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [line.rstrip("\n") for line in lines[-limit:]]
    except OSError:
        return []
