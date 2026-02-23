# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-23

"""
4ham Spectrum Analysis - Main Application Entry Point
======================================================

FastAPI application with modular architecture:
- REST API endpoints organized by domain (health, events, scan, settings, etc.)
- WebSocket handlers for real-time streaming
- Rate limiting and security middleware
- CORS configuration
- Static file serving for frontend
"""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Import API and WebSocket routers
from app.api import health, events, scan, settings, logs, exports, admin, decoders
from app.websocket import logs as ws_logs, events as ws_events, spectrum as ws_spectrum, status as ws_status


# ═══════════════════════════════════════════════════════════════════
# FastAPI Application Setup
# ═══════════════════════════════════════════════════════════════════

app = FastAPI(
    title="4ham Spectrum Analysis",
    description="Real-time spectrum monitoring and digital mode decoding for amateur radio",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# ═══════════════════════════════════════════════════════════════════
# Rate Limiting Configuration
# ═══════════════════════════════════════════════════════════════════

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ═══════════════════════════════════════════════════════════════════
# CORS Configuration
# ═══════════════════════════════════════════════════════════════════

# Configure allowed origins based on environment
cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
cors_enabled = os.getenv("CORS_ENABLED", "1").lower() in {"1", "true", "yes", "on"}

if cors_enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ═══════════════════════════════════════════════════════════════════
# Security Headers Middleware
# ═══════════════════════════════════════════════════════════════════

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all HTTP responses."""
    response = await call_next(request)
    
    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    # Remove server header to avoid information disclosure
    if "server" in response.headers:
        del response.headers["server"]
    
    return response

# ═══════════════════════════════════════════════════════════════════
# REST API Routers
# ═══════════════════════════════════════════════════════════════════

# Include all API routers with /api prefix
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(events.router, prefix="/api", tags=["Events"])
app.include_router(scan.router, prefix="/api/scan", tags=["Scan"])
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(logs.router, prefix="/api", tags=["Logs"])
app.include_router(exports.router, prefix="/api", tags=["Exports"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(decoders.router, prefix="/api", tags=["Decoders"])

# ═══════════════════════════════════════════════════════════════════
# WebSocket Routers
# ═══════════════════════════════════════════════════════════════════

# Include WebSocket handlers
app.include_router(ws_logs.router, tags=["WebSocket - Logs"])
app.include_router(ws_events.router, tags=["WebSocket - Events"])
app.include_router(ws_spectrum.router, tags=["WebSocket - Spectrum"])
app.include_router(ws_status.router, tags=["WebSocket - Status"])

# ═══════════════════════════════════════════════════════════════════
# Static File Serving (Frontend)
# ═══════════════════════════════════════════════════════════════════

# Serve frontend static files from /frontend directory
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

if FRONTEND_DIR.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(FRONTEND_DIR), html=True),
        name="frontend"
    )
