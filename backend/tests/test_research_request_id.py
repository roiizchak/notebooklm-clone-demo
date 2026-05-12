"""Gotcha pin: request_id_var must propagate into the BackgroundTask runner.

B-COR-09 pattern: FastAPI BackgroundTasks do not inherit the request's
contextvar context, so the chat router must capture rid = request_id_var.get()
outside the task body and call request_id_var.set(rid) inside the runner.
"""

from __future__ import annotations

from unittest.mock import MagicMock

NB = "11111111-1111-1111-1111-111111111111"
SESSION = "22222222-2222-2222-2222-222222222222"
REPORT = "44444444-4444-4444-4444-444444444441"
EXPECTED_RID = "rid-test-1234"


def test_request_id_var_propagates_into_research_background_task(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["chat_sessions"] = MagicMock(
        data=[{"id": SESSION, "notebook_id": NB, "title": "X"}]
    )
    fake_supabase.responses["sources"] = MagicMock(data=[{"id": "src1"}])

    msg_state = {"i": 0}

    def _messages(chain):
        msg_state["i"] += 1
        return [{"id": f"m-{msg_state['i']}"}]

    fake_supabase.responses["chat_messages"] = _messages

    rep_state = {"i": 0}

    def _reports(chain):
        rep_state["i"] += 1
        if any(op == "select" and args == ("id",) for (op, args, _) in chain):
            return []
        return [{"id": REPORT, "status": "pending"}]

    fake_supabase.responses["research_reports"] = _reports

    captured: dict = {}

    import app.routers.chat as chat_mod
    import app.services.research as rsv
    from app.middleware.request_id import request_id_var

    def _capture_rid(_report_id: str) -> None:
        captured["rid_inside_task"] = request_id_var.get()

    monkeypatch.setattr(rsv, "run_research_blocking", _capture_rid)

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/chat",
        headers={"X-Request-ID": EXPECTED_RID},
        json={"message": "Q", "mode": "research"},
    )
    assert r.status_code == 202
    assert captured.get("rid_inside_task") == EXPECTED_RID
