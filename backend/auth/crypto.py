"""Encryption utilities for sensitive data at rest."""

import os
import base64
import hashlib
from cryptography.fernet import Fernet
from typing import Optional

# Derive encryption key from secret
_ENCRYPTION_KEY: Optional[bytes] = None


def _get_encryption_key() -> bytes:
    """Get or derive the encryption key."""
    global _ENCRYPTION_KEY
    
    if _ENCRYPTION_KEY is not None:
        return _ENCRYPTION_KEY
    
    # Use dedicated encryption key or derive from JWT secret
    secret = os.environ.get("ENCRYPTION_KEY") or os.environ.get("JWT_SECRET", "dev-secret")
    
    # Derive a proper 32-byte key using PBKDF2
    key = hashlib.pbkdf2_hmac(
        'sha256',
        secret.encode('utf-8'),
        b'scopedocs-encryption-salt',
        100000,
        dklen=32
    )
    _ENCRYPTION_KEY = base64.urlsafe_b64encode(key)
    return _ENCRYPTION_KEY


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token for storage."""
    if not plaintext:
        return plaintext
    
    key = _get_encryption_key()
    f = Fernet(key)
    encrypted = f.encrypt(plaintext.encode('utf-8'))
    return base64.urlsafe_b64encode(encrypted).decode('utf-8')


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a stored token."""
    if not ciphertext:
        return ciphertext
    
    try:
        key = _get_encryption_key()
        f = Fernet(key)
        encrypted = base64.urlsafe_b64decode(ciphertext.encode('utf-8'))
        decrypted = f.decrypt(encrypted)
        return decrypted.decode('utf-8')
    except Exception:
        # If decryption fails, assume it's a legacy unencrypted token
        return ciphertext


def is_encrypted(value: str) -> bool:
    """Check if a value appears to be encrypted."""
    if not value:
        return False
    try:
        # Encrypted values are base64-encoded Fernet tokens
        decoded = base64.urlsafe_b64decode(value.encode('utf-8'))
        # Fernet tokens start with version byte and have specific structure
        return len(decoded) > 60 and decoded[0] == 128
    except Exception:
        return False
