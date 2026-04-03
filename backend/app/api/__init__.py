# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# API module

"""
API Module
==========
REST API routers for 4ham Spectrum Analysis.
"""

# Import routers for easy access
from app.api import health, events, scan, decoders, exports, settings, admin, logs, auth, analytics

__all__ = ["health", "events", "scan", "decoders", "exports", "settings", "admin", "logs", "auth", "analytics"]
