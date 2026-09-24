"""StorageService: the only module that talks to S3-compatible storage (docs/18)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

import aioboto3
import structlog
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode

log = structlog.get_logger()


@lru_cache
def _session() -> aioboto3.Session:
    return aioboto3.Session()


def _client_kwargs(public: bool) -> dict[str, Any]:
    s = get_settings()
    endpoint = (s.S3_PUBLIC_ENDPOINT if public else None) or s.S3_ENDPOINT
    kw: dict[str, Any] = {
        "region_name": s.S3_REGION,
        "config": Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if s.S3_FORCE_PATH_STYLE else "auto"},
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=60,
        ),
    }
    if endpoint:
        kw["endpoint_url"] = endpoint
    if s.S3_ACCESS_KEY and s.S3_SECRET_KEY:
        kw["aws_access_key_id"] = s.S3_ACCESS_KEY.get_secret_value()
        kw["aws_secret_access_key"] = s.S3_SECRET_KEY.get_secret_value()
    return kw


@asynccontextmanager
async def _client(public: bool = False) -> AsyncIterator[Any]:
    try:
        async with _session().client("s3", **_client_kwargs(public)) as c:
            yield c
    except (BotoCoreError, ClientError) as e:
        log.error("storage.error", error_type=type(e).__name__)
        raise AppError(ErrorCode.STORAGE_ERROR) from e


def bucket() -> str:
    return get_settings().S3_BUCKET


async def presigned_post(
    key: str, content_type: str, max_bytes: int, expires: int = 600
) -> dict[str, Any]:
    """Browser upload target with enforced content-length-range (docs/18 §4)."""
    async with _client(public=True) as c:
        result: dict[str, Any] = await c.generate_presigned_post(
            Bucket=bucket(),
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[["content-length-range", 1, max_bytes], {"Content-Type": content_type}],
            ExpiresIn=expires,
        )
        return result


async def presigned_get(
    key: str, *, filename: str | None = None, inline: bool = False, expires: int = 300
) -> str:
    params: dict[str, Any] = {"Bucket": bucket(), "Key": key}
    if filename:
        from urllib.parse import quote

        disposition = "inline" if inline else "attachment"
        params["ResponseContentDisposition"] = f"{disposition}; filename*=UTF-8''{quote(filename)}"
    async with _client(public=True) as c:
        url: str = await c.generate_presigned_url("get_object", Params=params, ExpiresIn=expires)
        return url


async def head(key: str) -> dict[str, Any] | None:
    async with _client() as c:
        try:
            res: dict[str, Any] = await c.head_object(Bucket=bucket(), Key=key)
            return res
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise


async def download_to(key: str, path: Path) -> None:
    async with _client() as c:
        obj = await c.get_object(Bucket=bucket(), Key=key)
        with path.open("wb") as fh:
            async for chunk in obj["Body"].iter_chunks(1024 * 256):
                fh.write(chunk)


async def get_bytes(key: str) -> bytes:
    async with _client() as c:
        obj = await c.get_object(Bucket=bucket(), Key=key)
        data: bytes = await obj["Body"].read()
        return data


async def put(key: str, data: bytes, content_type: str) -> None:
    async with _client() as c:
        await c.put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)


async def delete_prefix(prefix: str) -> int:
    """Deletes every object under prefix (the original and its derived/* objects)."""
    n = 0
    async with _client() as c:
        paginator = c.get_paginator("list_objects_v2")
        async for page in paginator.paginate(Bucket=bucket(), Prefix=prefix):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                await c.delete_objects(Bucket=bucket(), Delete={"Objects": keys, "Quiet": True})
                n += len(keys)
    return n
