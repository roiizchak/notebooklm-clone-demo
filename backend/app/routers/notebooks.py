"""Notebook CRUD."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.models.schemas import NotebookCreate, NotebookOut, NotebookUpdate
from app.services.auth import AuthUser, get_current_user
from app.services.supabase_client import get_supabase

router = APIRouter()


def _get_owned_or_404(notebook_id: str, user_id: str) -> dict:
    sb = get_supabase()
    res = (
        sb.table("notebooks")
        .select("*")
        .eq("id", notebook_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Notebook not found")
    return res.data[0]


@router.post("/notebooks", response_model=dict, status_code=201)
def create_notebook(payload: NotebookCreate, user: AuthUser = Depends(get_current_user)) -> dict:
    sb = get_supabase()
    res = (
        sb.table("notebooks")
        .insert(
            {
                "user_id": user.user_id,
                "name": payload.name,
                "emoji": payload.emoji,
                "description": payload.description,
            }
        )
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create notebook")
    return {"data": res.data[0]}


@router.get("/notebooks", response_model=dict)
def list_notebooks(user: AuthUser = Depends(get_current_user)) -> dict:
    sb = get_supabase()
    res = (
        sb.table("notebooks")
        .select("*")
        .eq("user_id", user.user_id)
        .order("updated_at", desc=True)
        .execute()
    )
    return {"data": res.data or []}


@router.get("/notebooks/{notebook_id}", response_model=dict)
def get_notebook(notebook_id: UUID, user: AuthUser = Depends(get_current_user)) -> dict:
    return {"data": _get_owned_or_404(notebook_id, user.user_id)}


@router.patch("/notebooks/{notebook_id}", response_model=dict)
def update_notebook(
    notebook_id: UUID,
    payload: NotebookUpdate,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    _get_owned_or_404(notebook_id, user.user_id)
    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update_data:
        return {"data": _get_owned_or_404(notebook_id, user.user_id)}

    sb = get_supabase()
    res = (
        sb.table("notebooks")
        .update(update_data)
        .eq("id", notebook_id)
        .eq("user_id", user.user_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to update notebook")
    return {"data": res.data[0]}


@router.delete("/notebooks/{notebook_id}", status_code=204)
def delete_notebook(notebook_id: UUID, user: AuthUser = Depends(get_current_user)) -> None:
    _get_owned_or_404(notebook_id, user.user_id)
    sb = get_supabase()
    sb.table("notebooks").delete().eq("id", notebook_id).eq(
        "user_id", user.user_id
    ).execute()
    return None
