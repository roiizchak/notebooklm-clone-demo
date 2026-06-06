"""Study materials endpoints (Phase 2).

Generates flashcards / quiz / study_guide / faq for a whole notebook,
persisted in `study_materials` (one row per kind, regenerate overwrites).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.services.audio import _gather_context  # reuse chunk aggregator
from app.services.auth import AuthUser, get_current_user
from app.services.gemini import STUDY_MODEL, get_gemini
from app.services.supabase_client import get_supabase
from app.services.usage import count_operations_24h, log_usage

# usage_logs operation_type values written per study kind (see log_usage call below).
_STUDY_OP_TYPES = ["study_flashcards", "study_quiz", "study_guide", "study_faq"]

log = logging.getLogger(__name__)
router = APIRouter()

# B-COR-05: per-call ceiling on the blocking Gemini study payload generator.
GEMINI_TIMEOUT_SECONDS = 60.0

StudyKindParam = Literal["flashcards", "quiz", "study_guide", "faq"]


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


def _validate_payload(kind: str, payload: dict) -> None:
    """Light shape check so a bad LLM response surfaces a 502 cleanly."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="LLM returned non-object")
    if kind == "flashcards":
        items = payload.get("flashcards")
        if not isinstance(items, list) or not items:
            raise HTTPException(status_code=502, detail="LLM returned no flashcards")
    elif kind == "quiz":
        items = payload.get("questions")
        if not isinstance(items, list) or not items:
            raise HTTPException(status_code=502, detail="LLM returned no quiz questions")
    elif kind == "study_guide":
        if not any(k in payload for k in ("summary", "key_concepts", "objectives")):
            raise HTTPException(status_code=502, detail="LLM returned malformed study guide")
    elif kind == "faq":
        items = payload.get("faqs")
        if not isinstance(items, list) or not items:
            raise HTTPException(status_code=502, detail="LLM returned no FAQs")


@router.post(
    "/notebooks/{notebook_id}/studies/{kind}/generate",
    status_code=201,
)
async def generate_study(
    notebook_id: UUID,
    kind: StudyKindParam,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    notebook_id = str(notebook_id)
    _verify_notebook_owned(notebook_id, user.user_id)

    # F1: per-user daily cap on paid study generations (best-effort guardrail).
    if (
        count_operations_24h(user.user_id, _STUDY_OP_TYPES)
        >= get_settings().studies_daily_limit_per_user
    ):
        raise HTTPException(
            status_code=429,
            detail="Daily study-generation limit reached. Try again later.",
        )

    ctx = _gather_context(notebook_id)
    if not ctx.text.strip():
        raise HTTPException(
            status_code=400,
            detail="Notebook has no ready sources to generate from",
        )

    gemini = get_gemini()
    try:
        payload, chat = await asyncio.wait_for(
            asyncio.to_thread(
                gemini.generate_study_payload, kind=kind, context=ctx.text
            ),
            timeout=GEMINI_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        log.warning(
            "studies generate timed out kind=%s notebook_id=%s timeout=%.0fs",
            kind, notebook_id, GEMINI_TIMEOUT_SECONDS,
        )
        raise HTTPException(
            status_code=504,
            detail=f"Study generation timed out after {int(GEMINI_TIMEOUT_SECONDS)}s",
        )
    _validate_payload(kind, payload)

    # Upsert: one row per (notebook_id, kind).
    sb = get_supabase()
    res = (
        sb.table("study_materials")
        .upsert(
            {
                "notebook_id": str(notebook_id),
                "user_id": user.user_id,
                "kind": kind,
                "payload": payload,
                "source_ids": ctx.source_ids,
                "model_used": STUDY_MODEL,
                "cost_usd": chat.usage.cost_usd,
            },
            on_conflict="notebook_id,kind",
        )
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to persist study material")

    log_usage(
        user_id=user.user_id,
        notebook_id=notebook_id,
        operation_type=f"study_{kind}",
        usage=chat.usage,
        metadata={"items": _count_items(kind, payload)},
    )
    return {"data": res.data[0]}


def _count_items(kind: str, payload: dict) -> int:
    if kind == "flashcards":
        return len(payload.get("flashcards", []) or [])
    if kind == "quiz":
        return len(payload.get("questions", []) or [])
    if kind == "faq":
        return len(payload.get("faqs", []) or [])
    return 1


@router.get("/notebooks/{notebook_id}/studies")
def list_studies(
    notebook_id: UUID, user: AuthUser = Depends(get_current_user)
) -> dict:
    _verify_notebook_owned(notebook_id, user.user_id)
    sb = get_supabase()
    res = (
        sb.table("study_materials")
        .select("*")
        .eq("notebook_id", notebook_id)
        .eq("user_id", user.user_id)
        .execute()
    )
    return {"data": res.data or []}


@router.get("/notebooks/{notebook_id}/studies/{kind}")
def get_study(
    notebook_id: UUID,
    kind: StudyKindParam,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    _verify_notebook_owned(notebook_id, user.user_id)
    sb = get_supabase()
    res = (
        sb.table("study_materials")
        .select("*")
        .eq("notebook_id", notebook_id)
        .eq("kind", kind)
        .eq("user_id", user.user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Study material not found")
    return {"data": res.data[0]}


@router.delete("/notebooks/{notebook_id}/studies/{kind}", status_code=204)
def delete_study(
    notebook_id: UUID,
    kind: StudyKindParam,
    user: AuthUser = Depends(get_current_user),
) -> None:
    _verify_notebook_owned(notebook_id, user.user_id)
    sb = get_supabase()
    sb.table("study_materials").delete().eq("notebook_id", notebook_id).eq(
        "kind", kind
    ).eq("user_id", user.user_id).execute()
    return None
