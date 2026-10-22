"""Object storage. One S3 bucket (RustFS in deployment) or a local directory for development."""

from __future__ import annotations

import mimetypes
import re
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from .config import get_settings

_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./\-]{0,400}$")


def check_key(key: str) -> str:
    if not _SAFE_KEY.match(key) or ".." in key or "//" in key:
        raise ValueError(f"对象键不合法：{key}")
    return key


def guess_mime(path_or_name: str) -> str:
    return mimetypes.guess_type(path_or_name)[0] or "application/octet-stream"


class ObjectStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.root = settings.data_dir / "objects"
        self.client = None
        if settings.s3_endpoint:
            import boto3

            self.client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
                region_name="us-east-1",
            )
            try:
                self.client.head_bucket(Bucket=self.bucket)
            except Exception:
                self.client.create_bucket(Bucket=self.bucket)
        else:
            self.root.mkdir(parents=True, exist_ok=True)

    def _local(self, key: str) -> Path:
        path = (self.root / check_key(key)).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError(f"对象键不合法：{key}")
        return path

    def put_file(self, key: str, source: Path, mime: str = "") -> None:
        check_key(key)
        mime = mime or guess_mime(source.name)
        if self.client:
            self.client.upload_file(str(source), self.bucket, key, ExtraArgs={"ContentType": mime})
            return
        dest = self._local(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)

    def put_bytes(self, key: str, data: bytes, mime: str = "") -> None:
        check_key(key)
        if self.client:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=mime or guess_mime(key))
            return
        dest = self._local(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def download_to(self, key: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self.client:
            self.client.download_file(self.bucket, check_key(key), str(dest))
        else:
            shutil.copyfile(self._local(key), dest)
        return dest

    def get_bytes(self, key: str) -> bytes:
        if self.client:
            return self.client.get_object(Bucket=self.bucket, Key=check_key(key))["Body"].read()
        return self._local(key).read_bytes()

    def local_path(self, key: str) -> Path | None:
        if self.client:
            return None
        path = self._local(key)
        return path if path.is_file() else None

    def stream(self, key: str, chunk: int = 1 << 20) -> Iterator[bytes]:
        body = self.client.get_object(Bucket=self.bucket, Key=check_key(key))["Body"]
        try:
            while data := body.read(chunk):
                yield data
        finally:
            body.close()

    def exists(self, key: str) -> bool:
        if self.client:
            try:
                self.client.head_object(Bucket=self.bucket, Key=check_key(key))
                return True
            except Exception:
                return False
        return self._local(key).is_file()


@lru_cache(maxsize=1)
def get_store() -> ObjectStore:
    return ObjectStore()


def reset_store() -> None:
    get_store.cache_clear()
