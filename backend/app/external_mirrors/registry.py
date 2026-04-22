# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""
Process-wide singletons for the external mirrors subsystem.

Created on lifespan startup; used by the admin REST API to register
plaintext tokens at create / rotate time and by the pusher loop to
read them.
"""

from __future__ import annotations

from typing import Optional

from .pusher import ExternalMirrorPusher, TokenCache
from .repository import ExternalMirrorRepository

_token_cache: Optional[TokenCache] = None
_repository: Optional[ExternalMirrorRepository] = None
_pusher: Optional[ExternalMirrorPusher] = None


def init(repository: ExternalMirrorRepository, pusher: ExternalMirrorPusher, token_cache: TokenCache) -> None:
    global _token_cache, _repository, _pusher
    _token_cache = token_cache
    _repository = repository
    _pusher = pusher


def get_token_cache() -> TokenCache:
    if _token_cache is None:
        raise RuntimeError("external_mirrors registry not initialised")
    return _token_cache


def get_repository() -> ExternalMirrorRepository:
    if _repository is None:
        raise RuntimeError("external_mirrors registry not initialised")
    return _repository


def get_pusher() -> ExternalMirrorPusher:
    if _pusher is None:
        raise RuntimeError("external_mirrors registry not initialised")
    return _pusher


def is_initialised() -> bool:
    return _repository is not None
