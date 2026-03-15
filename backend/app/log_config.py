# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Logging configuration with automatic rotation

"""
Logging Configuration
=====================
Centralized logging setup with automatic file rotation.

Features:
- RotatingFileHandler: prevents unbounded log file growth
- maxBytes: 10 MB per file (configurable via LOG_MAX_BYTES env var)
- backupCount: 5 backup files (configurable via LOG_BACKUP_COUNT env var)
- Total max disk usage: ~60 MB for logs (10 MB × 6 files)

Files:
- logs/backend.log (current)
- logs/backend.log.1 (most recent backup)
- logs/backend.log.2
- ...
- logs/backend.log.5 (oldest backup)
"""

import os
import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler


def setup_logging():
    """
    Configure logging with rotation for uvicorn and application loggers.
    
    Environment Variables:
    - LOG_FILE: path to log file (default: <project_root>/logs/backend.log)
    - LOG_MAX_BYTES: max bytes per log file (default: 10485760 = 10 MB)
    - LOG_BACKUP_COUNT: number of backup files to keep (default: 5)
    - LOG_LEVEL: logging level (default: INFO)
    """
    # Resolve log file path
    project_root = Path(__file__).resolve().parents[2]
    default_log_file = project_root / "logs" / "backend.log"
    log_file_str = os.getenv("LOG_FILE", str(default_log_file))
    log_file = Path(log_file_str).expanduser()
    
    # Validate and create parent directory
    if not log_file.is_absolute():
        log_file = default_log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Rotation parameters
    max_bytes = int(os.getenv("LOG_MAX_BYTES", 10 * 1024 * 1024))  # 10 MB default
    backup_count = int(os.getenv("LOG_BACKUP_COUNT", 5))
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    # Create rotating file handler
    file_handler = RotatingFileHandler(
        filename=str(log_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    
    # Console handler (stderr) for critical errors
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.WARNING)
    
    # Log format
    log_format = "%(levelname)-8s %(asctime)s %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, datefmt=date_format)
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Configure uvicorn loggers to use the same handlers
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.setLevel(log_level)
        logger.propagate = False
    
    # Log startup message
    root_logger.info(f"Logging configured: {log_file} (max {max_bytes // 1024 // 1024} MB, {backup_count} backups)")
    
    return log_file
