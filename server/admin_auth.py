"""Admin passwords stay hashed. Sessions are random tokens."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets


def hash_password(password: str, salt: str | None = None) -> str:
    if not password or len(password) < 8:
        raise ValueError("密码至少 8 位")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "scrypt" or not password:
        return False
    check = hash_password(password, salt).split("$", 2)[2]
    return hmac.compare_digest(check, digest)


def new_session() -> str:
    return secrets.token_urlsafe(32)


def bootstrap_password() -> str | None:
    value = os.environ.get("CVGEN_ADMIN_PASSWORD", "").strip()
    return value or None
