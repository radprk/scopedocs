"""Password hashing utilities."""

import hashlib
import secrets
import base64


def hash_password(password: str) -> str:
    """Hash a password with salt using PBKDF2."""
    salt = secrets.token_bytes(32)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        100000,  # iterations
        dklen=32
    )
    # Store salt + hash together
    return base64.b64encode(salt + key).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    try:
        decoded = base64.b64decode(hashed.encode('utf-8'))
        salt = decoded[:32]
        stored_key = decoded[32:]
        
        key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            100000,
            dklen=32
        )
        return secrets.compare_digest(key, stored_key)
    except Exception:
        return False
