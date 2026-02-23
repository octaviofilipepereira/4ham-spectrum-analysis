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

import sys
import getpass
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.core.auth import hash_password


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
