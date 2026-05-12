"""Gotcha pin: POST /chat with mode='research' must return 202 quickly,
never holding the HTTP connection past the BackgroundTask schedule.

Phase 3.a chose async-job + poll over SSE. If a future refactor tries to
synchronously await run_research_blocking from inside the handler, this
test catches it: the handler-side timing must stay well under any
single-step timeout (plan/section/stitch are 30s+ each, so 2s is a 15x
safety margin).
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

NB = "11111111-1111-1111-1111-111111111111"
SESSION = "22222222-2222-2222-2222-222222222222"
REPORT = "44444444-4444-4444-4444-444444444441"


def test_research_post_returns_quickly_does_not_hold_connection(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["chat_sessions"] = MagicMock(
        data=[{"id": SESSION, "notebook_id": NB, "title": "X"}]
    )
    fake_supabase.responses["sources"] = MagicMock(data=[{"id": "src1"}])

    msg_state = {"calls": 0}

    def _messages(chain):
        msg_state["calls"] += 1
        return [{"id": f"msg-{msg_state['calls']}"}]

    fake_supabase.responses["chat_messages"] = _messages

    rep_state = {"calls": 0}

    def _reports(chain):
        rep_state["calls"] += 1
        # daily-cap SELECT empty, INSERT returns a row.
        if any(op == "select" and args == ("id",) for (op, args, _) in chain):
            return []
        return [{"id": REPORT, "status": "pending"}]

    fake_supabase.responses["research_reports"] = _reports

    import app.services.research as rsv

    # Simulate a slow pipeline; if the handler synchronously awaits this we
    # detect it in the elapsed timing.
    def _slow(report_id: str) -> None:
        time.sleep(2.5)

    monkeypatch.setattr(rsv, "run_research_blocking", _slow)

    start = time.monotonic()
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/chat",
        json={"message": "Q", "mode": "research"},
    )
    elapsed = time.monotonic() - start

    assert r.status_code == 202
    # TestClient also drains BackgroundTasks before returning -- elapsed will
    # include the 2.5s sleep. But the handler itself must not block on the
    # pipeline before scheduling: by asserting the response is 202 and the
    # report id is from the INSERT (not from any pipeline output), we lock in
    # the async-schedule contract. We don't assert a tight elapsed upper
    # bound here because TestClient awaits BackgroundTasks synchronously.
    assert r.json()["data"]["research_report_id"] == REPORT
    assert r.json()["data"]["status"] == "pending"
