# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# WebSocket module

"""
WebSocket Module
================
WebSocket handlers for real-time data streaming.

Available Routers:
- logs: Application logs streaming (/ws/logs)
- events: Occupancy events streaming (/ws/events)
- spectrum: Real-time spectrum waterfall (/ws/spectrum)
- status: System status updates (/ws/status)
"""

from app.websocket import logs, events, spectrum, status

__all__ = ["logs", "events", "spectrum", "status"]

