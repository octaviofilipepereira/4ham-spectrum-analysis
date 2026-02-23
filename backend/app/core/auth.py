# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-23 16:00:00 UTC

"""
Authentication and security utilities.
"""

import base64
import os
from typing import Optional, Tuple

import bcrypt


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.
    
    Args:
        password: Plain text password to hash
        
    Returns:
        Bcrypt hashed password as string
    """
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(password: str, hashed_password: str) -> bool:
    """
    Verify a password against a bcrypt hash.
    
    Args:
        password: Plain text password to verify
        hashed_password: Bcrypt hashed password
        
    Returns:
        True if password matches, False otherwise
    """
    try:
        password_bytes = password.encode('utf-8')
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False


def parse_basic_auth(authorization: Optional[str]) -> Optional[Tuple[str, str]]:
    """
    Parse HTTP Basic Authentication header.
    
    Args:
        authorization: Authorization header value (e.g., "Basic dXNlcjpwYXNz")
        
    Returns:
        Tuple of (username, password) if valid, None otherwise
    """
    if not authorization:
        return None
    
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "basic":
        return None
    
    try:
        decoded = base64.b64decode(parts[1]).decode('utf-8')
        if ':' not in decoded:
            return None
        username, password = decoded.split(':', 1)
        return username, password
    except Exception:
        return None


def verify_basic_auth(
    authorization: Optional[str],
    expected_username: str,
    expected_password_hash: str
) -> bool:
    """
    Verify HTTP Basic Authentication with hashed password.
    
    Args:
        authorization: Authorization header value
        expected_username: Expected username
        expected_password_hash: Expected password hash (bcrypt)
        
    Returns:
        True if credentials are valid, False otherwise
    """
    credentials = parse_basic_auth(authorization)
    if not credentials:
        return False
    
    username, password = credentials
    if username != expected_username:
        return False
    
    return verify_password(password, expected_password_hash)


def verify_basic_auth_plaintext(
    authorization: Optional[str],
    expected_username: str,
    expected_password: str
) -> bool:
    """
    Verify HTTP Basic Authentication with plaintext password.
    
    DEPRECATED: Use verify_basic_auth with hashed passwords instead.
    This function is kept for backward compatibility only.
    
    Args:
        authorization: Authorization header value
        expected_username: Expected username
        expected_password: Expected password (plaintext)
        
    Returns:
        True if credentials are valid, False otherwise
    """
    credentials = parse_basic_auth(authorization)
    if not credentials:
        return False
    
    username, password = credentials
    return username == expected_username and password == expected_password


def generate_secure_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure random token.
    
    Args:
        length: Length of the token in bytes
        
    Returns:
        Hex-encoded random token
    """
    return os.urandom(length).hex()


# Migration helper: Check if a string is a bcrypt hash
def is_bcrypt_hash(value: str) -> bool:
    """
    Check if a string looks like a bcrypt hash.
    
    Args:
        value: String to check
        
    Returns:
        True if the string appears to be a bcrypt hash
    """
    return value.startswith('$2b$') or value.startswith('$2a$') or value.startswith('$2y$')


if __name__ == "__main__":
    # Example usage and testing
    print("Password Hashing Example:")
    print("-" * 50)
    
    # Hash a password
    plain_password = "MySecurePassword123!"
    hashed = hash_password(plain_password)
    print(f"Plain: {plain_password}")
    print(f"Hash:  {hashed}")
    print()
    
    # Verify correct password
    is_valid = verify_password(plain_password, hashed)
    print(f"Verify correct password: {is_valid}")
    
    # Verify incorrect password
    is_valid = verify_password("WrongPassword", hashed)
    print(f"Verify wrong password:   {is_valid}")
    print()
    
    # Generate secure token
    token = generate_secure_token()
    print(f"Secure token: {token}")
