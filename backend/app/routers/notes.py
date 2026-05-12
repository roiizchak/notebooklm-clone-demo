"""Notes endpoints (Phase 2).

Two note types:
  - 'written': user-authored. `original_message_id` must be null.
  - 'saved_response': saved from an assistant chat message. `original_message_id`
    is required and must belong to a chat session in the same notebook.

Pinned notes float to the top of the list view. Tags are stored as a JSONB
array but no filter UI ships in Phase 2 (free-form annotation only).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.schemas import NoteCreate, NoteUpdate
from app.services.auth import AuthUser, get_current_user
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


def _verify_chat_message_in_notebook(message_id: str, notebook_id: str) -> None:
    """Verify the chat message belongs to a session in the notebook."""
    sb = get_supabase()
    res = (
        sb.table("chat_messages")
        .select("id, session_id, chat_sessions!inner(notebook_id)")
        .eq("id", message_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=400, detail="Referenced chat message not found")
    sessions = res.data[0].get("chat_sessions")
    # supabase-py returns the joined row directly under the table name.
    nb = (
        sessions.get("notebook_id")
        if isinstance(sessions, dict)
        else (sessions[0].get("notebook_id") if isinstance(sessions, list) and sessions else None)
    )
    if nb != notebook_id:
        raise HTTPException(
            status_code=400,
            detail="Chat message does not belong to this notebook",
        )


def _get_owned_note_or_404(note_id: str, notebook_id: str, user_id: str) -> dict:
    sb = get_supabase()
    res = (
        sb.table("notes")
        .select("*")
        .eq("id", note_id)
        .eq("notebook_id", notebook_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Note not found")
    return res.data[0]


@router.post("/notebooks/{notebook_id}/notes", status_code=201)
def create_note(
    notebook_id: UUID,
    payload: NoteCreate,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    # UUID-in-body / Python-comparison discipline (B-COR-07).
    notebook_id = str(notebook_id)
    original_message_id = (
        str(payload.original_message_id)
        if payload.original_message_id is not None
        else None
    )
    _verify_notebook_owned(notebook_id, user.user_id)

    if payload.type == "written":
        if original_message_id:
            raise HTTPException(
                status_code=400,
                detail="written notes must not have original_message_id",
            )
    else:  # saved_response
        if not original_message_id:
            raise HTTPException(
                status_code=400,
                detail="saved_response notes require original_message_id",
            )
        _verify_chat_message_in_notebook(original_message_id, notebook_id)

    sb = get_supabase()
    res = (
        sb.table("notes")
        .insert(
            {
                "notebook_id": notebook_id,
                "user_id": user.user_id,
                "type": payload.type,
                "title": payload.title,
                "content": payload.content,
                "tags": payload.tags or [],
                "is_pinned": bool(payload.is_pinned),
                "original_message_id": original_message_id,
            }
        )
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create note")
    return {"data": res.data[0]}


@router.get("/notebooks/{notebook_id}/notes")
def list_notes(
    notebook_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthUser = Depends(get_current_user),
) -> dict:
    notebook_id = str(notebook_id)
    _verify_notebook_owned(notebook_id, user.user_id)
    sb = get_supabase()
    res = (
        sb.table("notes")
        .select("*")
        .eq("notebook_id", notebook_id)
        .eq("user_id", user.user_id)
        .order("is_pinned", desc=True)
        .order("updated_at", desc=True)
        .limit(limit)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {"data": res.data or []}


@router.get("/notebooks/{notebook_id}/notes/{note_id}")
def get_note(
    notebook_id: UUID,
    note_id: UUID,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    notebook_id = str(notebook_id)
    note_id = str(note_id)
    _verify_notebook_owned(notebook_id, user.user_id)
    return {"data": _get_owned_note_or_404(note_id, notebook_id, user.user_id)}


@router.patch("/notebooks/{notebook_id}/notes/{note_id}")
def update_note(
    notebook_id: UUID,
    note_id: UUID,
    payload: NoteUpdate,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    notebook_id = str(notebook_id)
    note_id = str(note_id)
    _verify_notebook_owned(notebook_id, user.user_id)
    _get_owned_note_or_404(note_id, notebook_id, user.user_id)

    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    sb = get_supabase()
    res = (
        sb.table("notes")
        .update(update_data)
        .eq("id", note_id)
        .eq("user_id", user.user_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to update note")
    return {"data": res.data[0]}


@router.delete("/notebooks/{notebook_id}/notes/{note_id}", status_code=204)
def delete_note(
    notebook_id: UUID,
    note_id: UUID,
    user: AuthUser = Depends(get_current_user),
) -> None:
    notebook_id = str(notebook_id)
    note_id = str(note_id)
    _verify_notebook_owned(notebook_id, user.user_id)
    _get_owned_note_or_404(note_id, notebook_id, user.user_id)
    sb = get_supabase()
    sb.table("notes").delete().eq("id", note_id).eq("user_id", user.user_id).execute()
    return None
