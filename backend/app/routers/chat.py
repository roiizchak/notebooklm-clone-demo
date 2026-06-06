"""Chat endpoints with RAG + multi-turn sessions.

POST /chat handles two modes (Phase 3.a):
- mode='chat' (default): single-shot RAG, sync response, 200 OK.
- mode='research': async deep research, enqueues BackgroundTask, returns 202.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.middleware.request_id import request_id_var
from app.models.schemas import ChatRequest, ChatResponse
from app.services import rag, research
from app.services.auth import AuthUser, get_current_user
from app.services.gemini import CHAT_DEFAULT, SUMMARY_MODEL, get_gemini
from app.services.supabase_client import get_supabase
from app.services.usage import count_operations_24h, log_usage

log = logging.getLogger(__name__)

router = APIRouter()

HISTORY_TURN_LIMIT = 10
CHAT_HISTORY_HARD_CAP = 200  # P-PRF-02. Cursor pagination deferred to Phase 3.


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


def _get_session_or_create(notebook_id, session_id) -> dict:
    sb = get_supabase()
    if session_id:
        res = (
            sb.table("chat_sessions")
            .select("*")
            .eq("id", str(session_id))
            .eq("notebook_id", str(notebook_id))
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Chat session not found")
        return res.data[0]

    # No session_id supplied → upsert the default session for this notebook.
    # Partial UNIQUE index (migration 011) makes concurrent first-message
    # POSTs collide; we catch the DB error and re-SELECT.
    try:
        ins = (
            sb.table("chat_sessions")
            .insert({"notebook_id": str(notebook_id), "title": None})
            .execute()
        )
        if ins.data:
            return ins.data[0]
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        if "23505" not in msg and "duplicate key" not in msg and "unique constraint" not in msg:
            raise

    existing = (
        sb.table("chat_sessions")
        .select("*")
        .eq("notebook_id", str(notebook_id))
        .is_("title", "null")
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]
    raise HTTPException(status_code=500, detail="Failed to create chat session")


def _load_history(session_id: str, limit: int = HISTORY_TURN_LIMIT) -> list[dict]:
    sb = get_supabase()
    res = (
        sb.table("chat_messages")
        .select("role,content,created_at")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = list(reversed(res.data or []))
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def _count_ready_sources(
    notebook_id: str, user_id: str, source_ids: list[str] | None
) -> int:
    """Count ready sources for this notebook, optionally filtered to a subset.

    Returns 0 if none — used by the research branch to reject early with 400
    instead of scheduling a BackgroundTask that will fail at the plan step.

    Note: ``sources`` has no ``user_id`` column (ownership flows via
    ``notebook_id -> notebooks.user_id``). The caller verifies notebook
    ownership before reaching here, so a notebook_id filter is sufficient.
    The ``user_id`` arg is accepted for symmetry but not used in the query.

    Bounded query: typical notebook has <50 ready sources, so SELECT-and-len
    is cheaper than the supabase-py count="exact" path which adds a HEAD
    round-trip and confuses test mocks (MagicMock.count auto-truthy).
    """
    _ = user_id  # unused; documented above
    sb = get_supabase()
    q = (
        sb.table("sources")
        .select("id")
        .eq("notebook_id", notebook_id)
        .eq("status", "ready")
        .limit(1)
    )
    if source_ids:
        q = q.in_("id", source_ids)
    res = q.execute()
    return len(res.data or [])


def _research_daily_count_24h(user_id: str) -> int:
    """Count research_reports rows for this user in the last 24h that should
    consume the daily quota: ready / partial / pending / researching.

    Failed reports do not punish the user.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    sb = get_supabase()
    res = (
        sb.table("research_reports")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .gte("created_at", cutoff)
        .in_("status", ["ready", "partial", "pending", "researching"])
        .execute()
    )
    # supabase-py returns count via res.count when count='exact'.
    return int(getattr(res, "count", None) or len(res.data or []))


def _research_branch(
    *,
    notebook_id: str,
    session: dict,
    payload: ChatRequest,
    background: BackgroundTasks,
    user: AuthUser,
) -> JSONResponse:
    """Handle POST /chat with mode='research'. Returns 202 + ResearchCreateAck."""
    sb = get_supabase()
    settings = get_settings()

    # 1. Pre-flight (subset only): if the user explicitly picked source_ids
    #    and none of them are ready, that's a user error worth surfacing now.
    #    A notebook with zero sources at all is FINE — the pipeline falls
    #    through to a knowledge-only report (no citations).
    source_ids_pref = list(payload.source_ids or []) if payload.source_ids else None
    if source_ids_pref:
        n_ready = _count_ready_sources(notebook_id, user.user_id, source_ids_pref)
        if n_ready == 0:
            raise HTTPException(
                status_code=400,
                detail="None of the selected sources are ready yet. "
                "Wait for ingestion to finish or pick different sources.",
            )

    # 2. Daily cap check.
    cap = settings.research_daily_limit_per_user
    used = _research_daily_count_24h(user.user_id)
    if used >= cap:
        raise HTTPException(
            status_code=429,
            detail=f"Daily research limit reached ({used}/{cap}). Try again later.",
        )

    # 3. Insert user message (mode='research').
    user_msg = (
        sb.table("chat_messages")
        .insert(
            {
                "session_id": session["id"],
                "role": "user",
                "content": payload.message,
                "mode": "research",
            }
        )
        .execute()
    )
    if not user_msg.data:
        raise HTTPException(status_code=500, detail="Failed to persist user message")

    # 4. Insert research_reports row. Catch 23505 -> 409 (B-COR-02 pattern).
    source_ids = list(payload.source_ids or []) if payload.source_ids else []
    try:
        report = research.enqueue_research_job(
            notebook_id=notebook_id,
            user_id=user.user_id,
            session_id=session["id"],
            question=payload.message,
            source_ids=source_ids,
        )
    except Exception as e:  # noqa: BLE001 — supabase-py wraps postgres 23505 in opaque APIError; inspect message text
        msg = str(e).lower()
        if "23505" in msg or "uq_research_reports_one_active_per_notebook" in msg:
            raise HTTPException(
                status_code=409,
                detail="A research report is already in flight for this notebook",
            ) from e
        log.exception(
            "enqueue_research_job failed notebook_id=%s",
            notebook_id,
        )
        raise

    report_id = str(report["id"])

    # 5. Insert assistant placeholder message linked to the report.
    asst_placeholder = (
        sb.table("chat_messages")
        .insert(
            {
                "session_id": session["id"],
                "role": "assistant",
                "content": "Researching…",
                "mode": "research",
                "research_report_id": report_id,
                "model_used": "gemini-3.1-pro-preview",
            }
        )
        .execute()
    )
    if not asst_placeholder.data:
        raise HTTPException(
            status_code=500, detail="Failed to persist assistant placeholder"
        )

    # 6. Schedule BackgroundTask with request-id contextvar capture (B-COR-09).
    rid = request_id_var.get()

    def _runner_with_rid(rid_capture: str, rid_target: str) -> None:
        request_id_var.set(rid_capture)
        research.run_research_blocking(rid_target)

    background.add_task(_runner_with_rid, rid, report_id)

    return JSONResponse(
        status_code=202,
        content={
            "data": {
                "message_id": asst_placeholder.data[0]["id"],
                "session_id": session["id"],
                "research_report_id": report_id,
                "status": "pending",
            }
        },
    )


def _backfill_session_title(session_id: str, first_message: str) -> None:
    """Generate a 4-6 word title for a brand-new session. Best-effort."""
    try:
        gemini = get_gemini()
        prompt = (
            "Summarize this user message into a 4-6 word title. "
            "No quotes, no trailing punctuation.\n\nMessage:\n"
            f"{first_message[:500]}"
        )
        result = gemini.generate_chat(
            system_instruction="You write concise titles.",
            history=[],
            user_message=prompt,
            model=SUMMARY_MODEL,
            temperature=0.2,
        )
        title = (result.content or "").strip().strip('"').strip("'")
        title = title.split("\n")[0][:80] if title else None
        if title:
            get_supabase().table("chat_sessions").update({"title": title}).eq(
                "id", session_id
            ).execute()
    except Exception as e:  # noqa: BLE001
        log.warning("title backfill failed: %s", e)


@router.post("/notebooks/{notebook_id}/chat")
async def chat(
    notebook_id: UUID,
    payload: ChatRequest,
    background: BackgroundTasks,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    notebook_id = str(notebook_id)
    _verify_notebook_owned(notebook_id, user.user_id)

    session = _get_session_or_create(notebook_id, payload.session_id)

    # Phase 3.a: deep research branch. Returns 202 + ResearchCreateAck and
    # does not touch the RAG pipeline below. (Research has its own 24h cap.)
    if payload.mode == "research":
        return _research_branch(
            notebook_id=notebook_id,
            session=session,
            payload=payload,
            background=background,
            user=user,
        )

    # F1: per-user daily cap on paid chat generations (best-effort guardrail).
    settings = get_settings()
    if (
        count_operations_24h(user.user_id, ["chat"])
        >= settings.chat_daily_limit_per_user
    ):
        raise HTTPException(
            status_code=429,
            detail="Daily chat limit reached. Try again later.",
        )

    is_new_session = session.get("title") is None

    history = _load_history(session["id"])

    sb = get_supabase()
    user_msg = (
        sb.table("chat_messages")
        .insert(
            {
                "session_id": session["id"],
                "role": "user",
                "content": payload.message,
            }
        )
        .execute()
    )
    if not user_msg.data:
        raise HTTPException(status_code=500, detail="Failed to persist user message")

    model = payload.model or CHAT_DEFAULT
    try:
        answer = await rag.answer(
            notebook_id=notebook_id,
            user_message=payload.message,
            history=history,
            source_ids=payload.source_ids,
            model=model,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("rag.answer failed")
        raise HTTPException(status_code=500, detail="Chat generation failed") from e

    asst = (
        sb.table("chat_messages")
        .insert(
            {
                "session_id": session["id"],
                "role": "assistant",
                "content": answer.content,
                "citations": [c.to_dict() for c in answer.citations],
                "source_ids_used": answer.source_ids_used,
                "model_used": answer.chat_usage.model_used,
                "input_tokens": answer.chat_usage.input_tokens,
                "output_tokens": answer.chat_usage.output_tokens,
                "cost_usd": round(answer.chat_usage.cost_usd, 6),
            }
        )
        .execute()
    )
    if not asst.data:
        raise HTTPException(status_code=500, detail="Failed to persist assistant message")

    log_usage(
        user_id=user.user_id,
        notebook_id=notebook_id,
        operation_type="chat_embed",
        usage=answer.embed_usage,
        metadata={"session_id": session["id"]},
    )
    log_usage(
        user_id=user.user_id,
        notebook_id=notebook_id,
        operation_type="chat",
        usage=answer.chat_usage,
        metadata={"session_id": session["id"]},
    )

    if is_new_session:
        background.add_task(_backfill_session_title, session["id"], payload.message)

    return {
        "data": {
            "message_id": asst.data[0]["id"],
            "session_id": session["id"],
            "content": answer.content,
            "citations": [c.to_dict() for c in answer.citations],
            "suggested_questions": [],
        },
        "usage": {
            "input_tokens": answer.chat_usage.input_tokens,
            "output_tokens": answer.chat_usage.output_tokens,
            "cost_usd": round(answer.chat_usage.cost_usd, 6),
            "model_used": answer.chat_usage.model_used,
        },
    }


@router.get("/notebooks/{notebook_id}/chat/sessions")
def list_sessions(
    notebook_id: UUID, user: AuthUser = Depends(get_current_user)
) -> dict:
    notebook_id = str(notebook_id)
    _verify_notebook_owned(notebook_id, user.user_id)
    sb = get_supabase()
    res = (
        sb.table("chat_sessions")
        .select("*")
        .eq("notebook_id", notebook_id)
        .order("updated_at", desc=True)
        .execute()
    )
    return {"data": res.data or []}


@router.get("/notebooks/{notebook_id}/chat/sessions/{session_id}")
def get_session(
    notebook_id: UUID,
    session_id: UUID,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    notebook_id = str(notebook_id)
    session_id = str(session_id)
    _verify_notebook_owned(notebook_id, user.user_id)
    sb = get_supabase()
    sess = (
        sb.table("chat_sessions")
        .select("*")
        .eq("id", session_id)
        .eq("notebook_id", notebook_id)
        .limit(1)
        .execute()
    )
    if not sess.data:
        raise HTTPException(status_code=404, detail="Chat session not found")

    msgs_res = (
        sb.table("chat_messages")
        .select("*")
        .eq("session_id", str(session_id))
        .order("created_at", desc=True)
        .limit(CHAT_HISTORY_HARD_CAP)
        .execute()
    )
    messages = list(reversed(msgs_res.data or []))
    return {"data": {"session": sess.data[0], "messages": messages}}


@router.delete(
    "/notebooks/{notebook_id}/chat/sessions/{session_id}", status_code=204
)
def delete_session(
    notebook_id: UUID,
    session_id: UUID,
    user: AuthUser = Depends(get_current_user),
) -> None:
    notebook_id = str(notebook_id)
    session_id = str(session_id)
    _verify_notebook_owned(notebook_id, user.user_id)
    sb = get_supabase()
    sess = (
        sb.table("chat_sessions")
        .select("id")
        .eq("id", session_id)
        .eq("notebook_id", notebook_id)
        .limit(1)
        .execute()
    )
    if not sess.data:
        raise HTTPException(status_code=404, detail="Chat session not found")
    # F7: chat_sessions has no user_id column (migration 004); ownership flows
    # via notebook_id -> notebooks.user_id, already verified above. The old
    # .eq("user_id", ...) filter targeted a nonexistent column.
    sb.table("chat_sessions").delete().eq("id", session_id).eq(
        "notebook_id", notebook_id
    ).execute()
    return None
