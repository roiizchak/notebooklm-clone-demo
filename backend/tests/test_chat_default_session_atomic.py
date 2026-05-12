"""B-COR-10: concurrent default-session-create returns the same row."""

from unittest.mock import MagicMock


def test_creates_default_session_when_none_exists(fake_supabase, auth_user_id) -> None:
    nb = "11111111-1111-1111-1111-111111111111"
    inserted = {"id": "22222222-2222-2222-2222-222222222222", "notebook_id": nb, "title": None}

    def _sessions_response(chain):
        ops = [c[0] for c in chain]
        if "insert" in ops:
            return [inserted]
        if "select" in ops:
            return [inserted]
        return []

    fake_supabase.responses["chat_sessions"] = _sessions_response

    from app.routers import chat as chat_mod

    s = chat_mod._get_session_or_create(notebook_id=nb, session_id=None)
    assert s["id"] == inserted["id"]


def test_reuses_default_session_on_unique_violation(fake_supabase) -> None:
    nb = "44444444-4444-4444-4444-444444444444"
    existing = {"id": "55555555-5555-5555-5555-555555555555", "notebook_id": nb, "title": None}
    state = {"insert_called": 0}

    def _sessions_response(chain):
        ops = [c[0] for c in chain]
        if "insert" in ops:
            state["insert_called"] += 1
            raise RuntimeError("23505: duplicate key value violates unique constraint")
        if "select" in ops:
            return [existing]
        return []

    fake_supabase.responses["chat_sessions"] = _sessions_response

    from app.routers import chat as chat_mod

    s = chat_mod._get_session_or_create(notebook_id=nb, session_id=None)
    assert s["id"] == existing["id"]
    assert state["insert_called"] == 1
