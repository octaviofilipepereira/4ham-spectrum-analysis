# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Dependencies module

"""
Dependencies Module
===================
Centralized application dependencies, state, auth, and utilities.
"""

# Re-export for convenience
from app.dependencies import state, auth, utils

__all__ = ["state", "auth", "utils"]
