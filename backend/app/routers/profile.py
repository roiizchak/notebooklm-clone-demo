"""User profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.models.schemas import ProfileUpdate
from app.services.auth import AuthUser, get_current_user
from app.services.supabase_client import get_supabase

router = APIRouter()


@router.get("/profile")
def get_profile(user: AuthUser = Depends(get_current_user)) -> dict:
    sb = get_supabase()
    res = sb.table("profiles").select("*").eq("id", user.user_id).limit(1).execute()
    if not res.data:
        # Fallback: trigger should always create the row, but handle missing.
        res = (
            sb.table("profiles")
            .insert({"id": user.user_id, "email": user.email})
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=500, detail="Profile not found")
    return {"data": res.data[0]}


@router.patch("/profile")
def update_profile(
    payload: ProfileUpdate, user: AuthUser = Depends(get_current_user)
) -> dict:
    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    sb = get_supabase()
    if not update_data:
        res = sb.table("profiles").select("*").eq("id", user.user_id).limit(1).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Profile not found")
        return {"data": res.data[0]}
    res = (
        sb.table("profiles")
        .update(update_data)
        .eq("id", user.user_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to update profile")
    return {"data": res.data[0]}
