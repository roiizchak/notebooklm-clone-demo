"""T-TST-05: chat session create / append + list + cross-session isolation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.gemini import Usage
from app.services.rag import Citation, RagAnswer

NB = "11111111-1111-1111-1111-111111111111"
SESS = "44444444-4444-4444-4444-444444444441"
USER_MSG_ID = "55555555-5555-5555-5555-555555555551"
ASST_MSG_ID = "55555555-5555-5555-5555-555555555552"


def _make_rag_answer() -> RagAnswer:
    return RagAnswer(
        content="stub answer [1]",
        citations=[
            Citation(
                number=1,
                chunk_id="c1",
                source_id="s1",
                source_name="Source 1",
                text_excerpt="hello world",
                metadata={},
                similarity=0.9,
            )
        ],
        source_ids_used=["s1"],
        chat_usage=Usage(
            input_tokens=100,
            output_tokens=50,
            model_used="gemini-3-flash-preview",
            cost_usd=0.001,
        ),
        embed_usage=Usage(
            input_tokens=10,
            output_tokens=0,
            model_used="gemini-embedding-2",
            cost_usd=0.000002,
        ),
    )


def test_chat_creates_session_and_returns_answer(
    fake_supabase, app_client, auth_user_id
) -> None:
    """First-message POST creates a session, appends user+assistant rows, returns RAG output."""
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )

    # chat_sessions handler: insert returns new session row; select returns same.
    inserted = {"id": SESS, "notebook_id": NB, "title": None}

    def _sessions(chain):
        ops = [c[0] for c in chain]
        if "insert" in ops:
            return [inserted]
        if "select" in ops:
            return [inserted]
        return []

    fake_supabase.responses["chat_sessions"] = _sessions

    # chat_messages handler: history select returns []; inserts return new rows.
    msg_state = {"insert_count": 0}

    def _messages(chain):
        ops = [c[0] for c in chain]
        if "insert" in ops:
            msg_state["insert_count"] += 1
            # 1st insert = user message, 2nd = assistant message
            mid = USER_MSG_ID if msg_state["insert_count"] == 1 else ASST_MSG_ID
            return [{"id": mid}]
        if "select" in ops:
            # _load_history call
            return []
        return []

    fake_supabase.responses["chat_messages"] = _messages

    import app.routers.chat as chat_mod
    import app.services.rag as rag_mod

    # rag.answer is async and accessed via `rag.answer(...)` in the router.
    async def _fake_answer(**kwargs):
        return _make_rag_answer()

    with patch.object(rag_mod, "answer", _fake_answer):
        # Also block the BackgroundTask title backfill so it doesn't call Gemini.
        with patch.object(chat_mod, "_backfill_session_title", lambda *a, **kw: None):
            r = app_client.post(
                f"/api/v1/notebooks/{NB}/chat", json={"message": "hello"}
            )

    assert r.status_code in (200, 201), r.text
    body = r.json()
    data = body["data"]
    assert data["session_id"] == SESS
    assert data["message_id"] == ASST_MSG_ID
    assert data["content"] == "stub answer [1]"
    assert data["citations"][0]["source_id"] == "s1"
    # Usage envelope is surfaced too.
    assert body["usage"]["model_used"] == "gemini-3-flash-preview"
    # Two inserts: user + assistant.
    assert msg_state["insert_count"] == 2


def test_chat_existing_session_reuses_id(
    fake_supabase, app_client, auth_user_id
) -> None:
    """Passing session_id loads that session instead of creating a new one."""
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    existing = {"id": SESS, "notebook_id": NB, "title": "Existing"}

    insert_calls = {"count": 0}

    def _sessions(chain):
        ops = [c[0] for c in chain]
        if "insert" in ops:
            insert_calls["count"] += 1
            return []
        if "select" in ops:
            return [existing]
        return []

    fake_supabase.responses["chat_sessions"] = _sessions

    def _messages(chain):
        ops = [c[0] for c in chain]
        if "insert" in ops:
            return [{"id": ASST_MSG_ID}]
        return []

    fake_supabase.responses["chat_messages"] = _messages

    import app.routers.chat as chat_mod
    import app.services.rag as rag_mod

    async def _fake_answer(**kwargs):
        return _make_rag_answer()

    with patch.object(rag_mod, "answer", _fake_answer):
        with patch.object(chat_mod, "_backfill_session_title", lambda *a, **kw: None):
            r = app_client.post(
                f"/api/v1/notebooks/{NB}/chat",
                json={"message": "hello", "session_id": SESS},
            )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["session_id"] == SESS
    # No new chat_sessions insert should have been issued.
    assert insert_calls["count"] == 0


def test_chat_rejects_cross_user_notebook(fake_supabase, app_client) -> None:
    """POST /chat 404s when the notebook is owned by a different user."""
    # _verify_notebook_owned filters by user_id; empty data => 404.
    fake_supabase.responses["notebooks"] = MagicMock(data=[])

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/chat", json={"message": "hello"}
    )
    assert r.status_code == 404


def test_list_sessions_returns_for_notebook(
    fake_supabase, app_client, auth_user_id
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["chat_sessions"] = MagicMock(
        data=[{"id": SESS, "notebook_id": NB, "title": "Hello"}]
    )
    r = app_client.get(f"/api/v1/notebooks/{NB}/chat/sessions")
    assert r.status_code == 200
    rows = r.json().get("data", [])
    assert any(row["id"] == SESS for row in rows)


def test_list_sessions_rejects_cross_user(fake_supabase, app_client) -> None:
    """Notebook owned by another user → 404 on session list."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[])
    r = app_client.get(f"/api/v1/notebooks/{NB}/chat/sessions")
    assert r.status_code == 404


def test_get_session_rejects_cross_user(fake_supabase, app_client) -> None:
    """Session exists but notebook isn't owned by caller → 404."""
    fake_supabase.responses["chat_sessions"] = MagicMock(
        data=[{"id": SESS, "notebook_id": NB, "title": "T"}]
    )
    fake_supabase.responses["notebooks"] = MagicMock(data=[])
    r = app_client.get(f"/api/v1/notebooks/{NB}/chat/sessions/{SESS}")
    assert r.status_code == 404


def test_get_session_returns_session_and_messages(
    fake_supabase, app_client, auth_user_id
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["chat_sessions"] = MagicMock(
        data=[{"id": SESS, "notebook_id": NB, "title": "Hello"}]
    )
    fake_supabase.responses["chat_messages"] = MagicMock(
        data=[
            {
                "id": USER_MSG_ID,
                "session_id": SESS,
                "role": "user",
                "content": "hi",
                "created_at": "2026-05-11T00:00:00Z",
            },
            {
                "id": ASST_MSG_ID,
                "session_id": SESS,
                "role": "assistant",
                "content": "hello!",
                "created_at": "2026-05-11T00:00:01Z",
            },
        ]
    )
    r = app_client.get(f"/api/v1/notebooks/{NB}/chat/sessions/{SESS}")
    assert r.status_code == 200
    payload = r.json()["data"]
    assert payload["session"]["id"] == SESS
    assert len(payload["messages"]) == 2
