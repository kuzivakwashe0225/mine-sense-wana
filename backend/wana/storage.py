"""Field photo storage: MinIO (S3) in production, the local photos folder otherwise.

Photos are never served directly from the bucket; the API reads them and checks the geologist role first.
"""
from __future__ import annotations

import io
import logging

from .config import PHOTOS
from .obs import DEPENDENCY_UP, PlatformError
from .settings import settings

_mc = None


def _minio():
    global _mc
    if _mc is None and settings.minio_endpoint:
        from minio import Minio
        _mc = Minio(settings.minio_endpoint, access_key=settings.minio_access_key,
                    secret_key=settings.minio_secret_key, secure=settings.minio_secure)
    return _mc


def put(name: str, data: bytes, content_type: str) -> None:
    mc = _minio()
    if not mc:
        PHOTOS.mkdir(parents=True, exist_ok=True)
        (PHOTOS / name).write_bytes(data)
        return
    try:
        mc.put_object(settings.minio_bucket, name, io.BytesIO(data), len(data), content_type=content_type)
        DEPENDENCY_UP.labels("minio").set(1)
    except Exception as e:  # noqa: BLE001
        DEPENDENCY_UP.labels("minio").set(0)
        raise PlatformError("Photo storage is not answering. The record was not saved; it stays on the phone.",
                            "minio_down") from e


def get(name: str) -> bytes | None:
    """None if the photo does not exist. Older photos may still be on local disk from before MinIO."""
    mc = _minio()
    if mc:
        try:
            r = mc.get_object(settings.minio_bucket, name)
            try:
                return r.read()
            finally:
                r.close()
                r.release_conn()
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", "") not in ("NoSuchKey", "NoSuchObject"):
                DEPENDENCY_UP.labels("minio").set(0)
                logging.getLogger("wana.storage").warning("minio read failed for %s: %s", name, e)
    p = (PHOTOS / name).resolve()
    if p.parent == PHOTOS.resolve() and p.exists():
        return p.read_bytes()
    return None


def ping() -> bool:
    mc = _minio()
    if not mc:
        return True
    try:
        ok = mc.bucket_exists(settings.minio_bucket)
        DEPENDENCY_UP.labels("minio").set(1 if ok else 0)
        return ok
    except Exception:  # noqa: BLE001
        DEPENDENCY_UP.labels("minio").set(0)
        return False
