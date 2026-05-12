"""B-COR-01: DELETE /chat/sessions must filter by user_id (defense-in-depth)."""

from unittest.mock import MagicMock


def test_delete_session_includes_user_id_filter(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[{"id": "11111111-1111-1111-1111-111111111111", "user_id": auth_user_id}])
    fake_supabase.responses["chat_sessions"] = MagicMock(data=[{"id": "44444444-4444-4444-4444-444444444441"}])

    r = app_client.delete("/api/v1/notebooks/11111111-1111-1111-1111-111111111111/chat/sessions/44444444-4444-4444-4444-444444444441")
    assert r.status_code == 204

    delete_chains = [
        chain for (table, chain) in fake_supabase.calls
        if table == "chat_sessions" and any(c[0] == "delete" for c in chain)
    ]
    assert delete_chains, "expected a delete on chat_sessions"
    eq_calls = [c[1] for c in delete_chains[-1] if c[0] == "eq"]
    assert ("user_id", auth_user_id) in eq_calls, f"missing user_id filter; got {eq_calls}"
