import hashlib
import secrets

PREFIX = "hs_"


def generate_token() -> str:
    """Generate a new API token."""
    return PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash an API token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()
