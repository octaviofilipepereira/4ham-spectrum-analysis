#!/usr/bin/env python3
# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-23 16:00:00 UTC

"""
Password hashing utility for 4ham-spectrum-analysis.

Usage:
    python hash_password.py [password]
    
If no password is provided, you will be prompted securely.
"""

import os
import sys
import getpass
from pathlib import Path

# Re-exec under the project venv if not already running there. This makes the
# script work without manual `pip install bcrypt` or venv activation, as long
# as install.sh has provisioned `.venv` next to this script's parent.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_VENV_PYTHON = _REPO_ROOT / ".venv" / "bin" / "python"
if (
    _VENV_PYTHON.is_file()
    and os.path.realpath(sys.executable) != os.path.realpath(str(_VENV_PYTHON))
):
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), __file__, *sys.argv[1:]])

# Add backend to path
sys.path.insert(0, str(_REPO_ROOT / "backend"))

try:
    from app.core.auth import hash_password  # type: ignore[import]
except ModuleNotFoundError as exc:
    print(f"ERROR: missing dependency ({exc.name}). Run install.sh first, or", file=sys.stderr)
    print("       inside the project venv: pip install -r backend/requirements.txt", file=sys.stderr)
    sys.exit(2)


def main():
    """Hash a password using bcrypt."""
    if len(sys.argv) > 1:
        password = sys.argv[1]
        print("WARNING: Password provided as command line argument (visible in history)")
        print()
    else:
        password = getpass.getpass("Enter password to hash: ")
        confirm = getpass.getpass("Confirm password: ")
        
        if password != confirm:
            print("ERROR: Passwords do not match!")
            sys.exit(1)
    
    if not password:
        print("ERROR: Password cannot be empty!")
        sys.exit(1)
    
    print("\nHashing password...")
    hashed = hash_password(password)
    
    print("\n" + "=" * 70)
    print("Bcrypt Hash:")
    print("=" * 70)
    print(hashed)
    print("=" * 70)
    print("\nAdd this to your .env file:")
    print(f"BASIC_AUTH_PASS={hashed}")
    print("\nNOTE: Make sure BASIC_AUTH_PASS_HASHED=1 is set in .env")
    print("=" * 70)


if __name__ == "__main__":
    main()
