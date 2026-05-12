"""Deep research mode endpoints (Phase 3.a).

The research job itself is kicked off from ``POST /chat`` with
``mode='research'`` (see ``app.routers.chat``). This router only exposes
GET / DELETE for the resulting ``research_reports`` rows.

Frontend polls ``GET /notebooks/{id}/research/{report_id}`` every ~2.5s
while ``status`` is in ``{pending, researching}`` and the document tab is
visible (P-PRF-06 visibility-gated polling).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

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


def _get_report_or_404(report_id: str, notebook_id: str, user_id: str) -> dict:
    sb = get_supabase()
    res = (
        sb.table("research_reports")
        .select("*")
        .eq("id", report_id)
        .eq("notebook_id", notebook_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Research report not found")
    return res.data[0]


@router.get("/notebooks/{notebook_id}/research")
def list_research(
    notebook_id: UUID,
    user: AuthUser = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """List research reports for a notebook, newest first. P-PRF-03 pagination."""
    notebook_id_str = str(notebook_id)
    _verify_notebook_owned(notebook_id_str, user.user_id)
    sb = get_supabase()
    res = (
        sb.table("research_reports")
        .select("*")
        .eq("notebook_id", notebook_id_str)
        .eq("user_id", user.user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {"data": res.data or []}


@router.get("/notebooks/{notebook_id}/research/{report_id}")
def get_research(
    notebook_id: UUID,
    report_id: UUID,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    """Poll target. Returns full report row including in-progress section state."""
    notebook_id_str = str(notebook_id)
    report_id_str = str(report_id)
    _verify_notebook_owned(notebook_id_str, user.user_id)
    row = _get_report_or_404(report_id_str, notebook_id_str, user.user_id)
    return {"data": row}


@router.delete("/notebooks/{notebook_id}/research/{report_id}", status_code=204)
def delete_research(
    notebook_id: UUID,
    report_id: UUID,
    user: AuthUser = Depends(get_current_user),
) -> None:
    """Owner-only delete. Linked chat_messages keep their content_md, FK becomes NULL."""
    notebook_id_str = str(notebook_id)
    report_id_str = str(report_id)
    _verify_notebook_owned(notebook_id_str, user.user_id)
    _get_report_or_404(report_id_str, notebook_id_str, user.user_id)
    sb = get_supabase()
    sb.table("research_reports").delete().eq("id", report_id_str).eq(
        "user_id", user.user_id
    ).execute()
    return None
