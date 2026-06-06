"""B-COR-01 / F7: DELETE /chat/sessions ownership-scopes the delete.

chat_sessions has no user_id column (migration 004); ownership flows via
notebook_id -> notebooks.user_id. The delete must therefore scope on both the
session id and the (ownership-verified) notebook_id, not a nonexistent user_id.
"""

from unittest.mock import MagicMock

NB = "11111111-1111-1111-1111-111111111111"
SESS = "44444444-4444-4444-4444-444444444441"


def test_delete_session_scopes_by_id_and_notebook(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[{"id": NB, "user_id": auth_user_id}])
    fake_supabase.responses["chat_sessions"] = MagicMock(data=[{"id": SESS}])

    r = app_client.delete(f"/api/v1/notebooks/{NB}/chat/sessions/{SESS}")
    assert r.status_code == 204

    delete_chains = [
        chain for (table, chain) in fake_supabase.calls
        if table == "chat_sessions" and any(c[0] == "delete" for c in chain)
    ]
    assert delete_chains, "expected a delete on chat_sessions"
    eq_calls = [c[1] for c in delete_chains[-1] if c[0] == "eq"]
    assert ("id", SESS) in eq_calls, f"missing session id filter; got {eq_calls}"
    assert ("notebook_id", NB) in eq_calls, f"missing notebook_id filter; got {eq_calls}"
    # Must NOT reference the nonexistent user_id column on chat_sessions.
    assert not any(k == "user_id" for k, _ in eq_calls), f"unexpected user_id filter; got {eq_calls}"
