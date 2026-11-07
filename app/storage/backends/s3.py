"""Files in an S3 bucket: Amazon S3, or any service that speaks the S3 protocol (MinIO, Cloudflare R2,
Backblaze B2, Wasabi, DigitalOcean Spaces, Ceph, ...). Set the endpoint address for anything that is not
Amazon, and turn on path-style addressing for the ones that need it (MinIO and most self-hosted servers).

boto3 is imported when first used, so installs that keep files on disk never load it.
"""

from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.storage.base import Storage, StorageError, valid_key
from app.storage.registry import register_backend

_DELETE_BATCH = 1000  # the most S3 deletes in one request
# What services without a usable multi-object delete answer with; the keys are then deleted one by one. The
# digest errors come from older servers (Scality CloudServer, ...) that expect Content-MD5, which newer boto3
# no longer sends for DeleteObjects (it sends a CRC32 checksum instead).
_NO_MULTI_DELETE = {
    "NotImplemented",
    "XNotImplemented",
    "MalformedXML",
    "MethodNotAllowed",
    "InvalidRequest",
    "501",
    "BadDigest",
    "InvalidDigest",
    "MissingContentMD5",
    "XAmzContentSHA256Mismatch",
}
_one_by_one: set[tuple[str, str]] = set()  # (endpoint, bucket) pairs found not to take multi-object deletes
_MISSING = {"NoSuchKey", "NotFound", "404"}
_EXPLAIN = {
    "InvalidAccessKeyId": "The access key was not recognized.",
    "SignatureDoesNotMatch": "The secret key does not match the access key (or the region is wrong).",
    "AuthorizationHeaderMalformed": "The region does not match the bucket's region.",
    "AccessDenied": "Access denied: this key may not read and write in the bucket.",
    "NoSuchBucket": "That bucket does not exist, or this key cannot see it.",
    "PermanentRedirect": "The bucket is in another region or at another address than the one configured.",
    "InvalidBucketName": "That is not a valid bucket name.",
    "RequestTimeTooSkewed": "The server's clock is too far from the storage service's clock.",
}


@lru_cache(maxsize=8)
def _client(endpoint: str, region: str, access_key: str, secret_key: str, path_style: bool) -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        region_name=region or "us-east-1",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if path_style else "auto"},
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=30,
            # Newer boto3 adds checksum headers that many S3-compatible services reject: only when required.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def _code(error: Exception) -> str:
    return str(getattr(error, "response", {}).get("Error", {}).get("Code", ""))


@register_backend
class S3Storage(Storage):
    key = "s3"

    def __init__(self) -> None:
        self.bucket = settings.s3_bucket
        folder = settings.s3_prefix.strip("/")
        self.prefix = f"{folder}/" if folder else ""

    @property
    def client(self) -> Any:
        return _client(
            settings.s3_endpoint_url,
            settings.s3_region,
            settings.s3_access_key_id,
            settings.s3_secret_access_key,
            settings.s3_path_style,
        )

    def is_configured(self) -> bool:
        return bool(settings.s3_bucket and settings.s3_access_key_id and settings.s3_secret_access_key)

    def _object(self, key: str) -> str:
        return self.prefix + valid_key(key)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(Bucket=self.bucket, Key=self._object(key), Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self._object(key))["Body"].read()
        except Exception as e:
            if _code(e) in _MISSING:
                raise FileNotFoundError(key) from None
            raise

    def delete(self, keys: Iterable[str]) -> None:
        objects = [self._object(k) for k in keys]
        where = (settings.s3_endpoint_url, self.bucket)
        for start in range(0, len(objects), _DELETE_BATCH):
            batch = objects[start : start + _DELETE_BATCH]
            if where in _one_by_one:
                self._delete_one_by_one(batch)
                continue
            try:
                result = self.client.delete_objects(
                    Bucket=self.bucket, Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True}
                )
            except Exception as e:
                if _code(e) not in _NO_MULTI_DELETE:
                    raise
                _one_by_one.add(where)  # do not try the batch call again for this service
                self._delete_one_by_one(batch)
                continue
            if result.get("Errors"):
                raise StorageError(
                    f"{len(result['Errors'])} files could not be deleted: {result['Errors'][0].get('Code')}"
                )

    def _delete_one_by_one(self, objects: list[str]) -> None:
        for k in objects:
            self.client.delete_object(Bucket=self.bucket, Key=k)

    def entries(self) -> Iterator[tuple[str, datetime]]:
        for page in self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=self.prefix
        ):
            for obj in page.get("Contents", []):
                yield obj["Key"][len(self.prefix) :], obj["LastModified"].astimezone(UTC)

    def explain(self, error: Exception) -> str:
        code = _code(error)
        if code in _EXPLAIN:
            return _EXPLAIN[code]
        name = type(error).__name__
        if name in ("EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError"):
            return "Could not reach the endpoint. Check its address and that the service is running."
        if name == "SSLError":
            return "The service's certificate was not accepted."
        if name in ("ParamValidationError", "InvalidEndpointURL", "ValueError", "InvalidRegionError"):
            return "Check the bucket name, region and endpoint address."
        return f"The storage service answered: {code or name}."
