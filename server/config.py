"""Process settings. Everything comes from the environment; nothing is global mutable state."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_dir: Path
    public_base: str
    secret_key: str
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    session_hours: int
    media_url_seconds: int
    exploration_priority_bonus: int
    web_dir: Path
    releases_dir: Path

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"


def _secret_key(data_dir: Path) -> str:
    value = os.environ.get("CVGEN_SECRET_KEY", "").strip()
    if value:
        return value
    path = data_dir / "secret.key"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(48)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = Path(os.environ.get("CVGEN_DATA", ROOT / "data"))
    return Settings(
        database_url=os.environ.get("CVGEN_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:55432/cvgen_dev"),
        data_dir=data_dir,
        public_base=os.environ.get("CVGEN_PUBLIC_BASE", "http://127.0.0.1:8080").rstrip("/"),
        secret_key=_secret_key(data_dir),
        s3_endpoint=os.environ.get("CVGEN_S3_ENDPOINT", os.environ.get("RUSTFS_ENDPOINT", "")),
        s3_access_key=os.environ.get("CVGEN_S3_ACCESS_KEY", os.environ.get("RUSTFS_ACCESS_KEY", "")),
        s3_secret_key=os.environ.get("CVGEN_S3_SECRET_KEY", os.environ.get("RUSTFS_SECRET_KEY", "")),
        s3_bucket=os.environ.get("CVGEN_S3_BUCKET", "cvgen"),
        session_hours=int(os.environ.get("CVGEN_SESSION_HOURS", "72")),
        media_url_seconds=int(os.environ.get("CVGEN_MEDIA_URL_SECONDS", "3600")),
        exploration_priority_bonus=int(os.environ.get("CVGEN_EXPLORATION_PRIORITY_BONUS", "10")),
        web_dir=ROOT / "web" / "dist",
        releases_dir=ROOT / "tools" / "dist",
    )


def reset_settings() -> None:
    get_settings.cache_clear()
