"""Supabase Storage helpers for signed URLs and object operations.

Wraps the service-role storage client. All paths are relative to the bucket
root and follow the canonical `{user_id}/...` folder-prefix isolation.
"""

from __future__ import annotations

import logging

from app.services.supabase_client import get_supabase

log = logging.getLogger(__name__)


def create_signed_upload_url(bucket: str, path: str) -> dict:
    """Issue a signed URL the client can PUT a file to.

    Supabase JS / Python SDK returns a dict like:
        {"signedUrl": "...", "token": "...", "path": "..."}
    The client uploads via the signed URL; the token (and JWT) authorizes
    the write. We always pass `upsert=False` so an existing object cannot
    be silently overwritten.
    """
    sb = get_supabase()
    res = sb.storage.from_(bucket).create_signed_upload_url(path)
    # supabase-py returns either dict-with-camelCase or attribute object;
    # normalise to a plain dict with both forms accessible.
    if isinstance(res, dict):
        signed_url = res.get("signedUrl") or res.get("signed_url") or ""
        token = res.get("token") or ""
    else:
        signed_url = (
            getattr(res, "signed_url", None)
            or getattr(res, "signedURL", None)
            or getattr(res, "signedUrl", None)
            or ""
        )
        token = getattr(res, "token", "") or ""
    if not signed_url:
        raise RuntimeError("Supabase did not return a signed upload URL")
    return {"signed_url": signed_url, "token": token, "path": path}


def create_signed_download_url(bucket: str, path: str, expires_in: int = 600) -> str:
    """Issue a signed URL the client can GET the file from."""
    sb = get_supabase()
    res = sb.storage.from_(bucket).create_signed_url(path, expires_in)
    if isinstance(res, dict):
        url = res.get("signedURL") or res.get("signedUrl") or res.get("signed_url") or ""
    else:
        url = (
            getattr(res, "signed_url", None)
            or getattr(res, "signedURL", None)
            or getattr(res, "signedUrl", None)
            or ""
        )
    if not url:
        raise RuntimeError("Supabase did not return a signed download URL")
    return url


def upload_bytes(bucket: str, path: str, data: bytes, content_type: str) -> None:
    """Upload `data` to `bucket` at `path` (no upsert)."""
    sb = get_supabase()
    sb.storage.from_(bucket).upload(
        path=path,
        file=data,
        file_options={"content-type": content_type, "upsert": "false"},
    )


def download_bytes(bucket: str, path: str) -> bytes:
    """Download an object as bytes."""
    sb = get_supabase()
    return sb.storage.from_(bucket).download(path)


def delete_object(bucket: str, path: str) -> None:
    """Best-effort delete. Logs and swallows storage errors."""
    if not path:
        return
    try:
        sb = get_supabase()
        sb.storage.from_(bucket).remove([path])
    except Exception as e:  # noqa: BLE001
        log.warning("storage delete failed for %s/%s: %s", bucket, path, e)


def object_exists(bucket: str, path: str) -> bool:
    """Check whether an object exists by listing its parent directory.

    Used by the upload-complete handler to verify the client actually PUT
    the file before kicking off ingestion.
    """
    if not path:
        return False
    try:
        sb = get_supabase()
        # Parent prefix vs. filename: storage list takes the directory.
        if "/" in path:
            prefix, name = path.rsplit("/", 1)
        else:
            prefix, name = "", path
        items = sb.storage.from_(bucket).list(prefix or None) or []
        return any(it.get("name") == name for it in items)
    except Exception as e:  # noqa: BLE001
        log.warning("storage list failed for %s/%s: %s", bucket, path, e)
        return False
