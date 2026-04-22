# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""External mirrors module: push-mode replication of dashboard data to remote hosts."""

from .http_client import (
    MirrorHttpClient,
    PushResult,
    canonical_json,
    sign_payload,
    verify_signature,
)
from .repository import (
    AUTO_DISABLE_THRESHOLD,
    ExternalMirror,
    ExternalMirrorRepository,
    MirrorNameConflictError,
    MirrorNotFoundError,
)

__all__ = [
    "AUTO_DISABLE_THRESHOLD",
    "ExternalMirror",
    "ExternalMirrorRepository",
    "MirrorHttpClient",
    "MirrorNameConflictError",
    "MirrorNotFoundError",
    "PushResult",
    "canonical_json",
    "sign_payload",
    "verify_signature",
]
