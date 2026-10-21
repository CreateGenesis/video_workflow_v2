"""Object storage. Local files stand in when RustFS is not configured."""

from __future__ import annotations

import os
from pathlib import Path

BUCKETS = ("references", "clips", "previews", "renders")


def local_media_path(root: Path, bucket: str, key: str) -> Path:
    if bucket not in BUCKETS or not key or key.startswith(("/", "\\")) or "\\" in key:
        raise ValueError("对象键不合法")
    base = (root / bucket).resolve()
    path = (base / key).resolve()
    if path != base and base not in path.parents:
        raise ValueError("对象键不合法")
    return path


class Storage:
    def __init__(self, root: Path):
        self.root = root
        self.client = None
        endpoint = os.environ.get("RUSTFS_ENDPOINT", "")
        if endpoint:
            import boto3

            self.client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=os.environ.get("RUSTFS_ACCESS_KEY", ""),
                aws_secret_access_key=os.environ.get("RUSTFS_SECRET_KEY", ""),
                region_name="us-east-1",
            )
            for bucket in BUCKETS:
                try:
                    self.client.create_bucket(Bucket=bucket)
                except Exception:
                    pass
        else:
            for bucket in BUCKETS:
                (root / bucket).mkdir(parents=True, exist_ok=True)

    def put(self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        if bucket not in BUCKETS:
            raise ValueError(bucket)
        local_media_path(self.root, bucket, key)
        if self.client:
            self.client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
        else:
            path = self.root / bucket / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return f"{bucket}/{key}"

    def get(self, object_key: str) -> bytes:
        bucket, key = object_key.split("/", 1)
        if self.client:
            return self.client.get_object(Bucket=bucket, Key=key)["Body"].read()
        return local_media_path(self.root, bucket, key).read_bytes()

    def signed_url(self, object_key: str | None, public_base: str) -> str:
        if not object_key:
            return ""
        if self.client:
            bucket, key = object_key.split("/", 1)
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=3600,
            )
        return f"{public_base.rstrip('/')}/media/{object_key}"
