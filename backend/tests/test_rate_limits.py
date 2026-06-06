"""F1: per-user daily caps on paid Gemini endpoints (chat + studies) return 429."""

from __future__ import annotations

from unittest.mock import MagicMock

NB = "11111111-1111-1111-1111-111111111111"
SESS = "44444444-4444-4444-4444-444444444441"


def test_chat_returns_429_when_daily_cap_reached(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    # Existing session so session-create succeeds before the cap guard runs.
    fake_supabase.responses["chat_sessions"] = MagicMock(
        data=[{"id": SESS, "notebook_id": NB, "title": "t"}]
    )

    import app.routers.chat as chat_mod
    from app.config import get_settings

    cap = get_settings().chat_daily_limit_per_user
    monkeypatch.setattr(chat_mod, "count_operations_24h", lambda *a, **k: cap)

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/chat", json={"message": "hello", "session_id": SESS}
    )
    assert r.status_code == 429, r.text
    assert "limit" in r.json()["detail"].lower()


def test_chat_allowed_below_cap(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    """Under the cap, the request proceeds past the 429 guard (not blocked)."""
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["chat_sessions"] = MagicMock(
        data=[{"id": SESS, "notebook_id": NB, "title": "t"}]
    )

    # chat_messages: history select -> []; inserts -> a row id.
    def _messages(chain):
        ops = [c[0] for c in chain]
        if "insert" in ops:
            return [{"id": "m1"}]
        return []

    fake_supabase.responses["chat_messages"] = _messages

    import app.routers.chat as chat_mod

    monkeypatch.setattr(chat_mod, "count_operations_24h", lambda *a, **k: 0)

    import app.services.rag as rag_mod
    from app.services.gemini import Usage
    from app.services.rag import RagAnswer

    async def _fake_answer(**kwargs):
        return RagAnswer(
            content="ok",
            citations=[],
            source_ids_used=[],
            chat_usage=Usage(model_used="gemini-3-flash-preview"),
            embed_usage=Usage(model_used="gemini-embedding-2"),
        )

    monkeypatch.setattr(rag_mod, "answer", _fake_answer)
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/chat",
        json={"message": "hello", "session_id": SESS},
    )
    assert r.status_code != 429, r.text
    assert r.status_code in (200, 201), r.text


def test_studies_returns_429_when_daily_cap_reached(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )

    import app.routers.studies as studies_mod
    from app.config import get_settings

    cap = get_settings().studies_daily_limit_per_user
    monkeypatch.setattr(studies_mod, "count_operations_24h", lambda *a, **k: cap)

    r = app_client.post(f"/api/v1/notebooks/{NB}/studies/flashcards/generate")
    assert r.status_code == 429, r.text
    assert "limit" in r.json()["detail"].lower()
