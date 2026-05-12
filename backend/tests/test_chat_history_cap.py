"""P-PRF-02: GET /chat/sessions/{id} caps messages at 200."""

from unittest.mock import MagicMock


def test_get_session_caps_messages_at_200(fake_supabase, app_client, auth_user_id) -> None:
    session_id = "44444444-4444-4444-4444-444444444441"
    notebook_id = "11111111-1111-1111-1111-111111111111"

    fake_supabase.responses["chat_sessions"] = MagicMock(
        data=[{"id": session_id, "notebook_id": notebook_id, "title": "Test"}]
    )
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": notebook_id, "user_id": auth_user_id}]
    )

    fake_msgs = [
        {
            "id": f"77777777-7777-7777-7777-77777777{i:04d}",
            "session_id": session_id,
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"m{i}",
            "citations": [],
            "source_ids_used": [],
            "created_at": "2026-05-11T00:00:00Z",
        }
        for i in range(200)
    ]
    fake_supabase.responses["chat_messages"] = MagicMock(data=fake_msgs)

    r = app_client.get(
        f"/api/v1/notebooks/{notebook_id}/chat/sessions/{session_id}"
    )
    assert r.status_code == 200
    body = r.json()
    # Response wraps payload under "data": {"session": ..., "messages": ...}
    payload = body.get("data", body)
    assert "messages" in payload
    assert len(payload["messages"]) <= 200

    msg_calls = [c for c in fake_supabase.calls if c[0] == "chat_messages"]
    assert msg_calls
    chain_ops = [op for (op, _, _) in msg_calls[-1][1]]
    assert "limit" in chain_ops, f"expected .limit in chain, got {chain_ops}"
