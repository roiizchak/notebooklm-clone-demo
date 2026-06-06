"""Source ingestion endpoints.

Each create endpoint inserts a `sources` row with `status='processing'`,
returns 202 with the source id immediately, and runs the ingest pipeline
via FastAPI BackgroundTasks. Frontend subscribes to Supabase Realtime
on the `sources` table for status updates.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
)

from app.middleware.request_id import request_id_var
from app.models.schemas import (
    SourceTextIn,
    SourceUrlIn,
    UploadCompleteIn,
    UploadInitIn,
)
from app.schemas.ingest import IngestPayload
from app.services.auth import AuthUser, get_current_user
from app.services.ingestion import run_ingest
from app.services.storage import (
    create_signed_upload_url,
    download_bytes,
    object_exists,
)
from app.services.supabase_client import get_supabase
from app.services.usage import log_usage

log = logging.getLogger(__name__)

router = APIRouter()

# Limits.
SOURCES_BUCKET = "sources"
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MiB — direct-upload via signed URL

# Accepted MIME types per source type.
_PDF_MIME = {"application/pdf"}
_DOCX_MIME = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_TXT_MIME = {"text/plain", "text/markdown"}

_ALLOWED_FILE_MIMES = _PDF_MIME | _DOCX_MIME | _TXT_MIME


def _source_type_for_mime(mime: str) -> str | None:
    if mime in _PDF_MIME:
        return "pdf"
    if mime in _DOCX_MIME:
        return "docx"
    if mime in _TXT_MIME:
        return "text"
    return None


def _content_matches_declared_type(source_type: str, head: bytes) -> bool:
    """F6a: verify magic bytes match the client-declared type.

    upload-init only checks the *declared* MIME; the file goes straight to
    Storage so the API never sniffs the real bytes. This catches a mismatch at
    ingest (e.g. an executable/HTML uploaded as application/pdf). Stdlib only —
    no python-magic (libmagic is unavailable on the Vercel runtime).
    """
    if source_type == "pdf":
        return head[:5] == b"%PDF-"
    if source_type == "docx":
        # DOCX is a ZIP container → ZIP local-file-header magic.
        return head[:4] == b"PK\x03\x04"
    # Text is validated separately via utf-8 decode; nothing to sniff.
    return True


def _verify_notebook_owned(notebook_id: str, user_id: str) -> None:
    sb = get_supabase()
    res = (
        sb.table("notebooks")
        .select("id")
        .eq("id", notebook_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Notebook not found")


def _create_source_row(
    *,
    notebook_id: str,
    source_type: str,
    name: str,
    status: str = "processing",
    metadata: dict | None = None,
    file_path: str | None = None,
    original_filename: str | None = None,
    mime_type: str | None = None,
    file_size: int | None = None,
) -> dict:
    sb = get_supabase()
    res = (
        sb.table("sources")
        .insert(
            {
                "notebook_id": str(notebook_id),
                "type": source_type,
                "name": name,
                "status": status,
                "metadata": metadata or {},
                "file_path": file_path,
                "original_filename": original_filename,
                "mime_type": mime_type,
                "file_size_bytes": file_size,
            }
        )
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create source row")
    return res.data[0]


def _mark_failed(source_id: str, error_message: str) -> None:
    """Update sources row to status='failed'. Retries once on transient error (B-COR-04)."""
    import time

    truncated = error_message[:500]
    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            get_supabase().table("sources").update(
                {"status": "failed", "error_message": truncated}
            ).eq("id", source_id).execute()
            if attempt == 2:
                log.warning(
                    "sources._mark_failed succeeded on retry source_id=%s", source_id
                )
            return
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt == 1:
                time.sleep(0.5)
                continue
    log.error(
        "STUCK_ROW sources._mark_failed exhausted retries source_id=%s err=%s",
        source_id,
        str(last_exc)[:200],
    )


def _sweep_stale_pending_uploads(notebook_id: str) -> None:
    """B-COR-03: best-effort cleanup of orphan pending sources.

    Direct-upload flow stamps a row with status='pending' before issuing a
    signed URL; if the client never calls upload-complete the row sits
    forever. Sweeps on every upload-init so cleanup happens organically
    without pg_cron. Storage objects are removed best-effort.

    Notebook ownership is already verified by the caller, so filtering
    on notebook_id alone is sufficient — sources lacks a user_id column.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    sb = get_supabase()
    try:
        stale = (
            sb.table("sources")
            .select("id, file_path")
            .eq("notebook_id", notebook_id)
            .eq("status", "pending")
            .lt("created_at", cutoff)
            .execute()
        )
    except Exception:  # noqa: BLE001
        log.exception("upload-init sweep: select failed")
        return
    rows = stale.data or []
    if not rows:
        return
    ids = [r["id"] for r in rows]
    paths = [r.get("file_path") for r in rows if r.get("file_path")]
    try:
        sb.table("sources").delete().in_("id", ids).execute()
    except Exception:  # noqa: BLE001
        log.exception("upload-init sweep: delete failed for ids=%s", ids)
        return
    from app.services.storage import delete_object

    for p in paths:
        delete_object(SOURCES_BUCKET, p)
    log.info("upload-init sweep: removed %d stale pending sources", len(ids))


def _mark_ready(
    source_id: str,
    *,
    token_count: int,
    source_guide: dict | None,
) -> None:
    update: dict[str, Any] = {
        "status": "ready",
        "token_count": token_count,
    }
    if source_guide is not None:
        update["source_guide"] = source_guide
    get_supabase().table("sources").update(update).eq("id", source_id).execute()


def _ingest_and_finalize_with_rid(rid: str, **kwargs: Any) -> None:
    """B-COR-09: re-establish the request_id contextvar inside the background
    task so log records emitted during ingest carry the originating rid."""
    request_id_var.set(rid)
    _ingest_and_finalize(**kwargs)


def _ingest_and_finalize(
    *,
    source_id: str,
    notebook_id: str,
    user_id: str,
    source_type: str,
    payload: dict,
    file_bytes: bytes | None,
    storage_path: str | None = None,
) -> None:
    """Sync wrapper used by BackgroundTasks; runs the async ingest pipeline.

    For binary sources uploaded via direct-to-Storage (PDF / DOCX / TXT-as-file),
    pass `storage_path` instead of `file_bytes`. The pipeline downloads the
    object from the `sources` bucket before running extraction.
    """
    import asyncio

    async def _run() -> None:
        bytes_to_use = file_bytes
        payload_to_use = dict(payload)
        if bytes_to_use is None and storage_path:
            try:
                bytes_to_use = await asyncio.to_thread(
                    download_bytes, SOURCES_BUCKET, storage_path
                )
            except Exception as e:  # noqa: BLE001
                log.exception("failed to fetch source bytes from storage: %s", storage_path)
                _mark_failed(source_id, f"storage download failed: {e}")
                return
            # F6a: sniff magic bytes against the declared type before extraction.
            if not _content_matches_declared_type(source_type, bytes_to_use[:8]):
                log.warning(
                    "content/type mismatch source_id=%s declared=%s", source_id, source_type
                )
                _mark_failed(source_id, "file content does not match declared type")
                return
            # Text uploads are stored as raw .txt; the ingestion pipeline
            # expects payload["content"] for text type, not file_bytes.
            if source_type == "text":
                try:
                    payload_to_use = {
                        "content": bytes_to_use.decode("utf-8", errors="replace")
                    }
                except Exception as e:  # noqa: BLE001
                    _mark_failed(source_id, f"could not decode text source: {e}")
                    return
                bytes_to_use = None
        try:
            result = await run_ingest(
                source_id=source_id,
                notebook_id=notebook_id,
                source_type=source_type,
                payload=payload_to_use,
                file_bytes=bytes_to_use,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("ingest failed for source %s", source_id)
            _mark_failed(source_id, str(e))
            return

        try:
            _mark_ready(
                source_id,
                token_count=result.total_tokens,
                source_guide=result.summary_payload,
            )
        except Exception:  # noqa: BLE001
            log.exception("failed to mark source %s ready", source_id)
            _mark_failed(source_id, "post-ingest update failed")
            return

        # Log usage. Failures are swallowed inside log_usage.
        log_usage(
            user_id=user_id,
            notebook_id=notebook_id,
            operation_type="source_embed",
            usage=result.embed_usage,
            metadata={"source_id": source_id, "chunks": result.chunks_created},
        )
        if result.summary_usage is not None:
            log_usage(
                user_id=user_id,
                notebook_id=notebook_id,
                operation_type="source_summary",
                usage=result.summary_usage,
                metadata={"source_id": source_id},
            )

    asyncio.run(_run())


# ---------- File upload (PDF / DOCX / TXT) via direct-to-Storage signed URL ----------
#
# Two-step flow replaces the previous multipart POST:
#   1) POST /sources/upload-init  -> server returns signed PUT URL + source row
#   2) Client PUTs the file directly to Supabase Storage
#   3) POST /sources/upload-complete -> server verifies object then enqueues ingest


@router.post("/notebooks/{notebook_id}/sources/upload-init", status_code=201)
def upload_init(
    notebook_id: UUID,
    payload: UploadInitIn,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    notebook_id = str(notebook_id)
    _verify_notebook_owned(notebook_id, user.user_id)

    mime = payload.mime_type
    if mime not in _ALLOWED_FILE_MIMES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {mime}")
    if payload.size > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50MB limit")
    source_type = _source_type_for_mime(mime)
    if source_type is None:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {mime}")

    # B-COR-03: clean up orphan pending uploads (>1h old) before creating a new one.
    _sweep_stale_pending_uploads(notebook_id)

    original_filename = payload.filename
    name = original_filename.rsplit("/", 1)[-1]

    # Insert row with status='uploading' before issuing the signed URL so we
    # have a stable source_id to put in the storage path.
    row = _create_source_row(
        notebook_id=notebook_id,
        source_type=source_type,
        name=name,
        status="pending",
        original_filename=original_filename,
        mime_type=mime,
        file_size=payload.size,
    )

    storage_path = f"{user.user_id}/{notebook_id}/{row['id']}/{original_filename}"
    try:
        signed = create_signed_upload_url(SOURCES_BUCKET, storage_path)
    except Exception:  # noqa: BLE001
        # Roll back the empty row so it doesn't pollute the source list.
        log.exception("upload-init: could not issue signed URL for %s", storage_path)
        try:
            get_supabase().table("sources").delete().eq("id", row["id"]).execute()
        except Exception:  # noqa: BLE001
            pass
        # Generic message — do not leak internal exception text to the client (F4).
        raise HTTPException(status_code=500, detail="Could not issue upload URL")

    # Persist storage_path on the row so upload-complete can locate it.
    get_supabase().table("sources").update({"file_path": storage_path}).eq(
        "id", row["id"]
    ).execute()

    return {
        "data": {
            "source_id": row["id"],
            "storage_path": storage_path,
            "signed_url": signed["signed_url"],
            "token": signed["token"],
            "expires_in": 600,
        }
    }


@router.post("/notebooks/{notebook_id}/sources/upload-complete", status_code=202)
def upload_complete(
    notebook_id: UUID,
    payload: UploadCompleteIn,
    background: BackgroundTasks,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    notebook_id = str(notebook_id)
    _verify_notebook_owned(notebook_id, user.user_id)

    sb = get_supabase()
    res = (
        sb.table("sources")
        .select("*")
        .eq("id", payload.source_id)
        .eq("notebook_id", notebook_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Source not found")
    row = res.data[0]

    if row["status"] not in ("pending", "failed"):
        # Already processing or done — idempotent no-op.
        return {"data": {"id": row["id"], "status": row["status"]}}

    storage_path = row.get("file_path")
    if not storage_path:
        raise HTTPException(status_code=400, detail="Source has no storage path")

    if not object_exists(SOURCES_BUCKET, storage_path):
        raise HTTPException(
            status_code=400,
            detail="Object not found in storage; client did not complete the upload",
        )

    # Flip status, enqueue ingest. The ingest task pulls the bytes from Storage.
    sb.table("sources").update({"status": "processing"}).eq("id", row["id"]).execute()

    source_type = row["type"]
    # Validate the hand-off payload at the boundary via IngestPayload.
    # For uploads the actual file bytes are fetched from Storage inside
    # `_ingest_and_finalize`; the dict mostly carries provenance. For text
    # uploads `_ingest_and_finalize` rebuilds the payload after decoding
    # the bytes, so the keys here are advisory rather than load-bearing.
    ingest_payload = IngestPayload(
        source_type="upload",
        name=row.get("name") or storage_path,
        storage_path=storage_path,
        original_filename=row.get("original_filename"),
        content_type=row.get("mime_type"),
        file_size_bytes=row.get("file_size_bytes"),
    )
    payload_for_ingest = ingest_payload.model_dump(mode="json", by_alias=True)

    rid = request_id_var.get()
    background.add_task(
        _ingest_and_finalize_with_rid,
        rid,
        source_id=row["id"],
        notebook_id=notebook_id,
        user_id=user.user_id,
        source_type=source_type,
        payload=payload_for_ingest,
        file_bytes=None,
        storage_path=storage_path,
    )
    return {"data": {"id": row["id"], "status": "processing"}}


# ---------- URL ----------


@router.post("/notebooks/{notebook_id}/sources/url", status_code=202)
def add_url_source(
    notebook_id: UUID,
    payload: SourceUrlIn,
    background: BackgroundTasks,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    notebook_id = str(notebook_id)
    _verify_notebook_owned(notebook_id, user.user_id)

    url = str(payload.url)
    row = _create_source_row(
        notebook_id=notebook_id,
        source_type="url",
        name=url,
        metadata={"url": url},
    )
    ingest_payload = IngestPayload(source_type="url", name=url, url=url)
    rid = request_id_var.get()
    background.add_task(
        _ingest_and_finalize_with_rid,
        rid,
        source_id=row["id"],
        notebook_id=notebook_id,
        user_id=user.user_id,
        source_type="url",
        payload=ingest_payload.model_dump(mode="json", by_alias=True),
        file_bytes=None,
    )
    return {"data": {"id": row["id"], "status": "processing"}}


# ---------- YouTube ----------


def _youtube_oembed(url: str) -> dict:
    """Fetch the video's title + author via YouTube's public oEmbed endpoint.

    No API key needed. Returns {} on any failure (best-effort).
    """
    import httpx

    try:
        r = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=8.0,
            follow_redirects=True,
        )
        if r.status_code == 200:
            data = r.json()
            return {
                "title": data.get("title"),
                "author": data.get("author_name"),
                "thumbnail": data.get("thumbnail_url"),
            }
    except Exception:  # noqa: BLE001
        pass
    return {}


@router.post("/notebooks/{notebook_id}/sources/youtube", status_code=202)
def add_youtube_source(
    notebook_id: UUID,
    payload: SourceUrlIn,
    background: BackgroundTasks,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    notebook_id = str(notebook_id)
    _verify_notebook_owned(notebook_id, user.user_id)

    url = str(payload.url)
    info = _youtube_oembed(url)
    name = info.get("title") or url
    metadata: dict = {"url": url}
    if info.get("author"):
        metadata["author"] = info["author"]
    if info.get("thumbnail"):
        metadata["thumbnail"] = info["thumbnail"]
    if info.get("title"):
        metadata["title"] = info["title"]

    row = _create_source_row(
        notebook_id=notebook_id,
        source_type="youtube",
        name=name,
        metadata=metadata,
    )
    ingest_payload = IngestPayload(source_type="youtube", name=name, url=url)
    rid = request_id_var.get()
    background.add_task(
        _ingest_and_finalize_with_rid,
        rid,
        source_id=row["id"],
        notebook_id=notebook_id,
        user_id=user.user_id,
        source_type="youtube",
        payload=ingest_payload.model_dump(mode="json", by_alias=True),
        file_bytes=None,
    )
    return {"data": {"id": row["id"], "status": "processing"}}


# ---------- Pasted text ----------


@router.post("/notebooks/{notebook_id}/sources/text", status_code=202)
def add_text_source(
    notebook_id: UUID,
    payload: SourceTextIn,
    background: BackgroundTasks,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    notebook_id = str(notebook_id)
    _verify_notebook_owned(notebook_id, user.user_id)

    row = _create_source_row(
        notebook_id=notebook_id,
        source_type="text",
        name=payload.name,
        metadata={},
    )
    ingest_payload = IngestPayload(
        source_type="text", name=payload.name, body=payload.content
    )
    rid = request_id_var.get()
    background.add_task(
        _ingest_and_finalize_with_rid,
        rid,
        source_id=row["id"],
        notebook_id=notebook_id,
        user_id=user.user_id,
        source_type="text",
        payload=ingest_payload.model_dump(mode="json", by_alias=True),
        file_bytes=None,
    )
    return {"data": {"id": row["id"], "status": "processing"}}


# ---------- List / Get / Delete ----------


@router.get("/notebooks/{notebook_id}/sources")
def list_sources(
    notebook_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthUser = Depends(get_current_user),
) -> dict:
    notebook_id = str(notebook_id)
    _verify_notebook_owned(notebook_id, user.user_id)
    sb = get_supabase()
    res = (
        sb.table("sources")
        .select("*")
        .eq("notebook_id", notebook_id)
        .order("created_at", desc=True)
        .limit(limit)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {"data": res.data or []}


@router.get("/notebooks/{notebook_id}/sources/{source_id}")
def get_source(
    notebook_id: UUID,
    source_id: UUID,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    _verify_notebook_owned(notebook_id, user.user_id)
    sb = get_supabase()
    res = (
        sb.table("sources")
        .select("*")
        .eq("id", source_id)
        .eq("notebook_id", notebook_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"data": res.data[0]}


@router.delete("/notebooks/{notebook_id}/sources/{source_id}", status_code=204)
def delete_source(
    notebook_id: UUID,
    source_id: UUID,
    user: AuthUser = Depends(get_current_user),
) -> None:
    _verify_notebook_owned(notebook_id, user.user_id)
    sb = get_supabase()
    res = (
        sb.table("sources")
        .select("file_path")
        .eq("id", source_id)
        .eq("notebook_id", notebook_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Source not found")

    file_path = res.data[0].get("file_path")
    sb.table("sources").delete().eq("id", source_id).eq(
        "notebook_id", notebook_id
    ).execute()

    if file_path:
        try:
            sb.storage.from_("sources").remove([file_path])
        except Exception as e:  # noqa: BLE001
            log.warning("storage delete failed for %s: %s", file_path, e)
    return None
