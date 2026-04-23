# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""
Encrypted persistence for mirror plaintext tokens.

Tokens are stored bcrypt-hashed at rest for verification, but the pusher
needs the *plaintext* to sign HMAC requests. Plaintext is held in memory
by ``TokenCache``; on process restart the cache is empty unless a master
key is configured to decrypt the persisted ciphertexts.

Master key is read from env ``MIRRORS_MASTER_KEY``:
  * If a 44-char urlsafe-base64 Fernet key, used directly.
  * Otherwise, treated as a passphrase and stretched via PBKDF2-HMAC-SHA256
    (200 000 iterations, fixed salt ``b"4ham-mirrors-v1"``).
  * Empty / unset disables persistence (memory-only — legacy behaviour).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PBKDF2_SALT = b"4ham-mirrors-v1"
_PBKDF2_ITER = 200_000
_ENV_VAR = "MIRRORS_MASTER_KEY"


class TokenVault:
    """Fernet-backed symmetric encryption for short secret strings."""

    def __init__(self, fernet) -> None:  # noqa: ANN001 — opaque cryptography object
        self._fernet = fernet

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")

    @classmethod
    def from_env(cls, var_name: str = _ENV_VAR) -> Optional["TokenVault"]:
        secret = os.environ.get(var_name, "").strip()
        if not secret:
            return None
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            logger.warning(
                "cryptography package not installed; %s ignored, mirror tokens are memory-only.",
                var_name,
            )
            return None

        # Try as raw Fernet key first (urlsafe-base64 encoding of 32 bytes).
        try:
            raw = base64.urlsafe_b64decode(secret.encode("ascii"))
            if len(raw) == 32:
                return cls(Fernet(secret.encode("ascii")))
        except Exception:
            pass

        # Fallback: derive a 32-byte key from the passphrase via PBKDF2.
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            secret.encode("utf-8"),
            _PBKDF2_SALT,
            _PBKDF2_ITER,
            dklen=32,
        )
        key = base64.urlsafe_b64encode(derived)
        return cls(Fernet(key))

    @classmethod
    def from_data_dir(cls, data_dir: os.PathLike | str) -> Optional["TokenVault"]:
        """Load (or auto-create) the master key from ``<data_dir>/.mirrors_master.key``.

        First call on a fresh install generates a Fernet key, writes it with
        permissions 0600, and returns a vault. Subsequent calls just read it.
        Returns ``None`` if the ``cryptography`` package is unavailable or if
        the key file cannot be created/read (e.g. read-only filesystem).
        """
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            logger.warning(
                "cryptography package not installed; mirror tokens are memory-only."
            )
            return None

        path = Path(data_dir) / ".mirrors_master.key"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                key_bytes = path.read_bytes().strip()
                if len(key_bytes) == 0:
                    raise ValueError("key file is empty")
            else:
                key_bytes = Fernet.generate_key()
                # Atomic write with 0600 permissions before rename.
                tmp = path.with_suffix(".key.tmp")
                fd = os.open(
                    str(tmp),
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                    0o600,
                )
                try:
                    os.write(fd, key_bytes + b"\n")
                finally:
                    os.close(fd)
                os.replace(str(tmp), str(path))
                logger.info(
                    "External mirrors: generated new master key at %s (mode 0600).",
                    path,
                )
            # Defensive: tighten perms in case the file was created by hand.
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return cls(Fernet(key_bytes))
        except Exception as exc:
            logger.warning(
                "External mirrors: failed to load/create master key at %s (%s); "
                "tokens will be memory-only.",
                path,
                exc,
            )
            return None
