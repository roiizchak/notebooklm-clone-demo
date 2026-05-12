"""Phase 3.a chat router branch: POST /chat with mode='research'.

Covers:
- 202 ack with research_report_id when mode='research' and capacity available
- BackgroundTask scheduled with the report id
- 409 when partial-UNIQUE collision (B-COR-02 23505) bubbles up
- 429 when daily cap reached
- 'chat' mode is unaffected (zero behavior change)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

NB = "11111111-1111-1111-1111-111111111111"
SESSION = "22222222-2222-2222-2222-222222222222"
REPORT = "44444444-4444-4444-4444-444444444441"
USER_MSG_ID = "55555555-5555-5555-5555-555555555551"
ASST_MSG_ID = "55555555-5555-5555-5555-555555555552"


def _owned_notebook(user_id: str) -> dict:
    return {"id": NB, "user_id": user_id}


def _session_row() -> dict:
    return {"id": SESSION, "notebook_id": NB, "title": "Existing session"}


def test_research_branch_returns_202_and_schedules_task(
    fake_supabase, app_client, auth_user_id, monkeypatch
):
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["sources"] = MagicMock(data=[{"id": "src1"}])

    state = {"chat_sessions": 0, "chat_messages": 0, "research_reports": 0}

    def _sessions(chain):
        state["chat_sessions"] += 1
        return [_session_row()]

    def _messages(chain):
        state["chat_messages"] += 1
        # 1st insert = user; 2nd insert = assistant placeholder.
        if state["chat_messages"] == 1:
            return [{"id": USER_MSG_ID}]
        return [{"id": ASST_MSG_ID}]

    def _reports(chain):
        state["research_reports"] += 1
        # 1st = daily-cap count (SELECT, empty); 2nd = INSERT new report.
        if any(op == "select" and args == ("id",) for (op, args, _) in chain):
            return []
        return [{"id": REPORT, "status": "pending"}]

    fake_supabase.responses["chat_sessions"] = _sessions
    fake_supabase.responses["chat_messages"] = _messages
    fake_supabase.responses["research_reports"] = _reports

    scheduled: list[str] = []
    import app.services.research as rsv

    def _capture(report_id: str) -> None:
        scheduled.append(report_id)

    monkeypatch.setattr(rsv, "run_research_blocking", _capture)

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/chat",
        json={"message": "Deep dive on methods", "mode": "research"},
    )
    assert r.status_code == 202, r.text
    body = r.json()["data"]
    assert body["research_report_id"] == REPORT
    assert body["session_id"] == SESSION
    assert body["status"] == "pending"
    # BackgroundTask ran via TestClient after response.
    assert scheduled == [REPORT]


def test_research_branch_returns_409_on_duplicate_inflight(
    fake_supabase, app_client, auth_user_id, monkeypatch
):
    """If enqueue_research_job raises because of partial UNIQUE collision."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["chat_sessions"] = MagicMock(data=[_session_row()])
    fake_supabase.responses["chat_messages"] = MagicMock(data=[{"id": USER_MSG_ID}])
    fake_supabase.responses["sources"] = MagicMock(data=[{"id": "src1"}])
    fake_supabase.responses["research_reports"] = MagicMock(data=[])  # daily-cap count = 0

    import app.routers.chat as chat_mod

    def _explode(**_kwargs):
        raise RuntimeError(
            "duplicate key value violates unique constraint "
            "\"uq_research_reports_one_active_per_notebook\" (SQLSTATE 23505)"
        )

    monkeypatch.setattr(chat_mod.research, "enqueue_research_job", _explode)

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/chat",
        json={"message": "Dup attempt", "mode": "research"},
    )
    assert r.status_code == 409, r.text
    assert "in flight" in r.json()["detail"].lower()


def test_research_branch_returns_429_when_daily_cap_hit(
    fake_supabase, app_client, auth_user_id, monkeypatch
):
    """If _research_daily_count_24h returns >= cap, 429 with Retry-After-ish msg."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["chat_sessions"] = MagicMock(data=[_session_row()])
    fake_supabase.responses["sources"] = MagicMock(data=[{"id": "src1"}])

    import app.routers.chat as chat_mod

    monkeypatch.setattr(chat_mod, "_research_daily_count_24h", lambda user_id: 10)

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/chat",
        json={"message": "Over cap", "mode": "research"},
    )
    assert r.status_code == 429, r.text
    assert "daily research limit" in r.json()["detail"].lower()


def test_research_branch_passes_source_ids_subset(
    fake_supabase, app_client, auth_user_id, monkeypatch
):
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["chat_sessions"] = MagicMock(data=[_session_row()])
    fake_supabase.responses["chat_messages"] = MagicMock(data=[{"id": USER_MSG_ID}])
    fake_supabase.responses["sources"] = MagicMock(data=[{"id": "src-1"}])

    state = {"reports": 0}

    def _reports(chain):
        state["reports"] += 1
        if any(op == "select" and args == ("id",) for (op, args, _) in chain):
            return []
        return [{"id": REPORT, "status": "pending"}]

    fake_supabase.responses["research_reports"] = _reports

    captured_kwargs: dict = {}
    import app.routers.chat as chat_mod

    def _capture(**kw):
        captured_kwargs.update(kw)
        return {"id": REPORT, "status": "pending"}

    monkeypatch.setattr(chat_mod.research, "enqueue_research_job", _capture)
    monkeypatch.setattr(chat_mod.research, "run_research_blocking", lambda _: None)

    subset = ["src-1", "src-2"]
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/chat",
        json={"message": "Subset", "mode": "research", "source_ids": subset},
    )
    assert r.status_code == 202, r.text
    assert captured_kwargs.get("source_ids") == subset


def test_research_branch_accepts_sourceless_notebook_for_knowledge_mode(
    fake_supabase, app_client, auth_user_id, monkeypatch
):
    """Sourceless notebook is OK: pipeline runs in knowledge-only mode and
    produces a report without citations. Pre-flight only rejects an explicit
    source_ids subset with zero ready matches."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["chat_sessions"] = MagicMock(data=[_session_row()])
    fake_supabase.responses["sources"] = MagicMock(data=[])  # zero ready — OK

    msg_state = {"i": 0}

    def _messages(chain):
        msg_state["i"] += 1
        return [{"id": f"m-{msg_state['i']}"}]

    rep_state = {"i": 0}

    def _reports(chain):
        rep_state["i"] += 1
        if any(op == "select" and args == ("id",) for (op, args, _) in chain):
            return []
        return [{"id": REPORT, "status": "pending"}]

    fake_supabase.responses["chat_messages"] = _messages
    fake_supabase.responses["research_reports"] = _reports

    import app.services.research as rsv
    monkeypatch.setattr(rsv, "run_research_blocking", lambda _id: None)

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/chat",
        json={"message": "What is quantum entanglement?", "mode": "research"},
    )
    assert r.status_code == 202, r.text
    assert r.json()["data"]["research_report_id"] == REPORT


def test_research_branch_returns_400_when_selected_subset_not_ready(
    fake_supabase, app_client, auth_user_id
):
    """source_ids subset provided but none of them are ready -> 400."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["chat_sessions"] = MagicMock(data=[_session_row()])
    fake_supabase.responses["sources"] = MagicMock(data=[])

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/chat",
        json={"message": "Q", "mode": "research", "source_ids": ["s1"]},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"].lower()
    assert "selected" in detail or "subset" in detail or "not ready" in detail


def test_chat_mode_default_still_works(
    fake_supabase, app_client, auth_user_id, monkeypatch
):
    """Backwards-compat: omitting `mode` defaults to 'chat' and runs the RAG path."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["chat_sessions"] = MagicMock(data=[_session_row()])

    msg_state = {"calls": 0}

    def _messages(chain):
        msg_state["calls"] += 1
        # 1st = history SELECT (empty); 2nd = user INSERT; 3rd = assistant INSERT.
        if msg_state["calls"] == 1:
            return []
        if msg_state["calls"] == 2:
            return [{"id": USER_MSG_ID}]
        return [{"id": ASST_MSG_ID}]

    fake_supabase.responses["chat_messages"] = _messages

    import app.routers.chat as chat_mod
    from app.services.gemini import Usage
    from app.services.rag import RagAnswer

    async def _fake_answer(**kwargs):
        return RagAnswer(
            content="hi",
            citations=[],
            source_ids_used=[],
            chat_usage=Usage(input_tokens=1, output_tokens=1, model_used="g", cost_usd=0.0),
            embed_usage=Usage(input_tokens=1, output_tokens=0, model_used="e", cost_usd=0.0),
        )

    monkeypatch.setattr(chat_mod.rag, "answer", _fake_answer)

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/chat",
        json={"message": "regular chat"},
    )
    # 200 OK with synchronous body, not 202.
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["session_id"] == SESSION
    assert "research_report_id" not in body
