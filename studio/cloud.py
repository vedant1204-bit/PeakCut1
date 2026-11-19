"""Optional online storage for finished clips (any S3-compatible bucket: Railway Bucket, Cloudflare R2, AWS S3).

Set PEAKCUT_S3_BUCKET, PEAKCUT_S3_ENDPOINT, PEAKCUT_S3_ACCESS_KEY and PEAKCUT_S3_SECRET_KEY (and PEAKCUT_S3_REGION
if the service needs one). Every finished clip (.mp4) and its cover (.jpg) is then uploaded and the local copy is
deleted, so the disk only holds what is being worked on. Without these settings nothing here does anything.

Keys mirror the path inside the data folder, so a clip at <data>/users/u1/jobs/j1/clips/clip01.mp4 is stored under
users/u1/jobs/j1/clips/clip01.mp4."""
import logging
import os
import tempfile
import threading
from pathlib import Path

from . import config

log = logging.getLogger("peakcut.cloud")
_local = threading.local()


def enabled() -> bool:
    return bool(config.env("PEAKCUT_S3_BUCKET") and config.env("PEAKCUT_S3_ACCESS_KEY") and config.env("PEAKCUT_S3_SECRET_KEY"))


def _client():
    c = getattr(_local, "c", None)
    if c is None:
        import boto3
        from botocore.config import Config
        c = _local.c = boto3.client(
            "s3", endpoint_url=config.env("PEAKCUT_S3_ENDPOINT") or None,
            region_name=config.env("PEAKCUT_S3_REGION") or "auto",
            aws_access_key_id=config.env("PEAKCUT_S3_ACCESS_KEY"), aws_secret_access_key=config.env("PEAKCUT_S3_SECRET_KEY"),
            config=Config(signature_version="s3v4", s3={"addressing_style": config.env("PEAKCUT_S3_ADDRESSING") or "virtual"},
                          retries={"max_attempts": 5, "mode": "standard"}))
    return c


def _bucket() -> str:
    return config.env("PEAKCUT_S3_BUCKET")


def key_for(path) -> str:
    return Path(path).resolve().relative_to(config.DATA_DIR.resolve()).as_posix()


def store(path, delete_local: bool = False) -> bool:
    """Back up a file to S3. Never remove local data unless upload and size verification succeed.

    Returns False when S3 is disabled or fails. Live recording uses this without deletion while
    a clip may still be reading the segment.
    """
    p = Path(path)
    if not enabled() or not p.is_file():
        return False
    types = {".mp4": "video/mp4", ".ts": "video/mp2t", ".jpg": "image/jpeg",
             ".jpeg": "image/jpeg", ".mov": "video/quicktime", ".webm": "video/webm"}
    try:
        size = p.stat().st_size
        _client().upload_file(str(p), _bucket(), key_for(p),
                              ExtraArgs={"ContentType": types.get(p.suffix.lower(), "application/octet-stream")})
        remote = _client().head_object(Bucket=_bucket(), Key=key_for(p))
        if remote.get("ContentLength") != size:
            raise IOError("Cloud upload size did not match the original")
        if delete_local:
            p.unlink(missing_ok=True)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("could not upload %s, keeping it on disk: %s", p.name, e)
        return False


def push(*paths) -> None:
    """Upload finished clips and delete local copies only when safe."""
    for p in paths:
        if Path(p).is_file():
            store(p, delete_local=True)


def exists_remote(path) -> bool:
    if not enabled():
        return False
    try:
        _client().head_object(Bucket=_bucket(), Key=key_for(path))
        return True
    except Exception:  # noqa: BLE001
        return False


def url(path, download_name: str = "", seconds: int = 3600) -> str:
    """A temporary link to the stored file, or "" if it is not stored online."""
    if not exists_remote(path):
        return ""
    params = {"Bucket": _bucket(), "Key": key_for(path)}
    if download_name:
        params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
    return _client().generate_presigned_url("get_object", Params=params, ExpiresIn=seconds)


def fetch(path) -> bool:
    """Make sure the file is on disk, downloading it if it only exists online. True if it was downloaded."""
    p = Path(path)
    if p.is_file() or not enabled():
        return False
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".part", dir=p.parent)
        os.close(fd)
        try:
            _client().download_file(_bucket(), key_for(p), tmp)
            Path(tmp).replace(p)
        finally:
            Path(tmp).unlink(missing_ok=True)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("could not download %s: %s", p.name, e)
        return False


def drop_local(path) -> None:
    """Remove a local copy of a clip that is safely stored online."""
    if enabled() and Path(path).is_file() and exists_remote(path):
        Path(path).unlink(missing_ok=True)


def remove(*paths) -> None:
    if not enabled():
        return
    for p in paths:
        try:
            _client().delete_object(Bucket=_bucket(), Key=key_for(p))
        except Exception as e:  # noqa: BLE001
            log.warning("could not delete %s online: %s", p, e)


def remove_prefix(folder) -> None:
    """Delete everything stored online under a folder (a video, a creator or an account being deleted)."""
    if not enabled():
        return
    try:
        prefix = key_for(folder).rstrip("/") + "/"
        for page in _client().get_paginator("list_objects_v2").paginate(Bucket=_bucket(), Prefix=prefix):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                _client().delete_objects(Bucket=_bucket(), Delete={"Objects": objs})
    except Exception as e:  # noqa: BLE001
        log.warning("could not clean up online files under %s: %s", folder, e)
