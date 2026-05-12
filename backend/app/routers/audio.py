"""Audio overview endpoints (Phase 2).

POST /generate enqueues a BackgroundTask. Frontend polls GET on the row
until status becomes 'ready' or 'failed'. GET /url returns a 10-min
signed download URL the browser uses for the <audio> element.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.middleware.request_id import request_id_var
from app.models.schemas import AudioGenerateIn
from app.services.audio import (
    AUDIO_BUCKET,
    enqueue_audio_generation,
    run_audio_generation_blocking,
)
from app.services.auth import AuthUser, get_current_user
from app.services.storage import create_signed_download_url, delete_object
from app.services.supabase_client import get_supabase

log = logging.getLogger(__name__)
router = APIRouter()


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


def _get_audio_or_404(audio_id: str, notebook_id: str, user_id: str) -> dict:
    sb = get_supabase()
    res = (
        sb.table("audio_overviews")
        .select("*")
        .eq("id", audio_id)
        .eq("notebook_id", notebook_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Audio overview not found")
    return res.data[0]


@router.post("/notebooks/{notebook_id}/audio/generate", status_code=202)
def generate_audio(
    notebook_id: UUID,
    payload: AudioGenerateIn,
    background: BackgroundTasks,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    notebook_id = str(notebook_id)
    _verify_notebook_owned(notebook_id, user.user_id)

    if payload.target_minutes not in (5, 10, 15):
        raise HTTPException(status_code=400, detail="target_minutes must be 5, 10, or 15")

    # B-COR-02: dedup. One active job per notebook at a time.
    sb = get_supabase()
    active = (
        sb.table("audio_overviews")
        .select("id,status")
        .eq("notebook_id", notebook_id)
        .eq("user_id", user.user_id)
        .in_("status", ["pending", "generating"])
        .limit(1)
        .execute()
    )
    if active.data:
        raise HTTPException(
            status_code=409,
            detail="An audio overview is already being generated for this notebook",
        )

    try:
        row = enqueue_audio_generation(
            notebook_id=notebook_id,
            user_id=user.user_id,
            target_minutes=int(payload.target_minutes),
            custom_instructions=payload.custom_instructions,
        )
    except Exception as e:  # noqa: BLE001 — supabase-py wraps postgres unique-violation 23505 in opaque APIError; must inspect message text
        msg = str(e).lower()
        if "23505" in msg or "uq_audio_overviews_one_active_per_notebook" in msg:
            raise HTTPException(
                status_code=409,
                detail="An audio overview is already being generated for this notebook",
            )
        log.exception("enqueue_audio_generation failed for notebook=%s", notebook_id)
        raise

    rid = request_id_var.get()

    def _runner_with_rid(audio_id: str) -> None:
        request_id_var.set(rid)
        run_audio_generation_blocking(audio_id)

    background.add_task(_runner_with_rid, row["id"])
    return {"data": {"id": row["id"], "status": row["status"]}}


@router.get("/notebooks/{notebook_id}/audio")
def list_audio(
    notebook_id: UUID, user: AuthUser = Depends(get_current_user)
) -> dict:
    _verify_notebook_owned(notebook_id, user.user_id)
    sb = get_supabase()
    res = (
        sb.table("audio_overviews")
        .select("*")
        .eq("notebook_id", notebook_id)
        .eq("user_id", user.user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return {"data": res.data or []}


@router.get("/notebooks/{notebook_id}/audio/{audio_id}")
def get_audio(
    notebook_id: UUID,
    audio_id: UUID,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    _verify_notebook_owned(notebook_id, user.user_id)
    return {"data": _get_audio_or_404(audio_id, notebook_id, user.user_id)}


@router.get("/notebooks/{notebook_id}/audio/{audio_id}/url")
def get_audio_url(
    notebook_id: UUID,
    audio_id: UUID,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    _verify_notebook_owned(notebook_id, user.user_id)
    row = _get_audio_or_404(audio_id, notebook_id, user.user_id)
    if row.get("status") != "ready" or not row.get("audio_path"):
        raise HTTPException(status_code=409, detail="Audio not ready")
    url = create_signed_download_url(AUDIO_BUCKET, row["audio_path"], expires_in=600)
    return {"data": {"signed_url": url, "expires_in": 600}}


@router.delete("/notebooks/{notebook_id}/audio/{audio_id}", status_code=204)
def delete_audio(
    notebook_id: UUID,
    audio_id: UUID,
    user: AuthUser = Depends(get_current_user),
) -> None:
    _verify_notebook_owned(notebook_id, user.user_id)
    row = _get_audio_or_404(audio_id, notebook_id, user.user_id)
    sb = get_supabase()
    sb.table("audio_overviews").delete().eq("id", audio_id).eq(
        "user_id", user.user_id
    ).execute()
    if row.get("audio_path"):
        delete_object(AUDIO_BUCKET, row["audio_path"])
    return None
