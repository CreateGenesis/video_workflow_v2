"""Passwords, opaque tokens, signed media links, webhook signatures, and secrets at rest."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

SESSION_PREFIX = "cvs_"
DEVICE_PREFIX = "cvd_"
API_KEY_PREFIX = "cvk_"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


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
    if scheme != "scrypt" or not password or len(password) < 8:
        return False
    check = hash_password(password, salt).split("$", 2)[2]
    return hmac.compare_digest(check, digest)


def new_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_user_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_user_code(code: str) -> str:
    cleaned = "".join(ch for ch in code.upper() if ch.isalnum())
    if len(cleaned) != 8:
        return ""
    return f"{cleaned[:4]}-{cleaned[4:]}"


def _key(purpose: str) -> bytes:
    return hmac.new(get_settings().secret_key.encode("utf-8"), purpose.encode("utf-8"), hashlib.sha256).digest()


def sign_media(artifact_id: str, expires: int | None = None) -> tuple[int, str]:
    expires = expires or int(time.time()) + get_settings().media_url_seconds
    message = f"{artifact_id}:{expires}".encode("utf-8")
    signature = hmac.new(_key("media"), message, hashlib.sha256).hexdigest()[:32]
    return expires, signature


def verify_media(artifact_id: str, expires: int, signature: str) -> bool:
    if expires < int(time.time()):
        return False
    _expires, expected = sign_media(artifact_id, expires)
    return hmac.compare_digest(expected, signature or "")


def media_url(artifact_id: str | None, absolute: bool = False) -> str:
    if not artifact_id:
        return ""
    expires, signature = sign_media(artifact_id)
    path = f"/media/{artifact_id}?exp={expires}&sig={signature}"
    return f"{get_settings().public_base}{path}" if absolute else path


def webhook_signature(body: bytes, timestamp: int, secret: str) -> str:
    """HMAC-SHA256 over "<timestamp>.<body>" with the receiver's shared secret."""
    message = f"{timestamp}.".encode("utf-8") + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def new_webhook_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_key("secrets")))


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("密钥无法解密，CVGEN_SECRET_KEY 可能变了") from exc


def mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 4:
        return "••••"
    return "••••" + secret[-4:]
