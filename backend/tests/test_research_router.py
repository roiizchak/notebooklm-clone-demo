"""Phase 3.a router: research GET / DELETE.

Pipeline cases (concurrency 409, daily-cap 429) live in Phase C alongside
the chat-router branch that owns research-job creation.
"""

from unittest.mock import MagicMock

NB = "11111111-1111-1111-1111-111111111111"
NB_OTHER = "11111111-1111-1111-1111-1111111111ff"
REPORT = "44444444-4444-4444-4444-444444444441"


def _owned_notebook(user_id: str) -> dict:
    return {"id": NB, "user_id": user_id}


def _report_row(user_id: str, status: str = "ready") -> dict:
    return {
        "id": REPORT,
        "notebook_id": NB,
        "user_id": user_id,
        "session_id": None,
        "question": "What are the key findings?",
        "source_ids": [],
        "status": status,
        "plan": None,
        "sections": [],
        "content_md": "TL;DR..." if status == "ready" else None,
        "citations": [],
        "model_plan": None,
        "model_sections": None,
        "model_stitch": None,
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
        "error": None,
        "created_at": "2026-05-11T19:30:00Z",
        "updated_at": "2026-05-11T19:30:00Z",
        "completed_at": "2026-05-11T19:31:00Z" if status == "ready" else None,
    }


def test_list_research_returns_paginated_rows(
    fake_supabase, app_client, auth_user_id
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["research_reports"] = MagicMock(
        data=[_report_row(auth_user_id), _report_row(auth_user_id, status="researching")]
    )

    r = app_client.get(f"/api/v1/notebooks/{NB}/research?limit=10&offset=0")
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert len(rows) == 2

    chain = [c for c in fake_supabase.calls if c[0] == "research_reports"][-1][1]
    ops = [c[0] for c in chain]
    assert "limit" in ops
    assert "range" in ops
    eq_args = [(c[1][0], str(c[1][1])) for c in chain if c[0] == "eq"]
    assert ("notebook_id", NB) in eq_args
    assert ("user_id", auth_user_id) in eq_args


def test_list_research_404_when_notebook_not_owned(fake_supabase, app_client) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[])
    r = app_client.get(f"/api/v1/notebooks/{NB}/research")
    assert r.status_code == 404


def test_list_research_422_on_bad_uuid(app_client) -> None:
    r = app_client.get("/api/v1/notebooks/not-a-uuid/research")
    assert r.status_code == 422


def test_get_research_returns_full_row(
    fake_supabase, app_client, auth_user_id
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["research_reports"] = MagicMock(
        data=[_report_row(auth_user_id, status="researching")]
    )

    r = app_client.get(f"/api/v1/notebooks/{NB}/research/{REPORT}")
    assert r.status_code == 200, r.text
    row = r.json()["data"]
    assert row["id"] == REPORT
    assert row["status"] == "researching"


def test_get_research_404_cross_user(fake_supabase, app_client, auth_user_id) -> None:
    """SELECT returns nothing because user_id filter excludes the report."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["research_reports"] = MagicMock(data=[])

    r = app_client.get(f"/api/v1/notebooks/{NB}/research/{REPORT}")
    assert r.status_code == 404


def test_get_research_422_on_bad_uuid(app_client) -> None:
    r = app_client.get(f"/api/v1/notebooks/{NB}/research/not-a-uuid")
    assert r.status_code == 422


def test_delete_research_succeeds_for_owner(
    fake_supabase, app_client, auth_user_id
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["research_reports"] = MagicMock(data=[_report_row(auth_user_id)])

    r = app_client.delete(f"/api/v1/notebooks/{NB}/research/{REPORT}")
    assert r.status_code == 204

    delete_calls = [
        c for c in fake_supabase.calls
        if c[0] == "research_reports" and any(op == "delete" for (op, _, _) in c[1])
    ]
    assert delete_calls, "expected a delete on research_reports"
    chain = delete_calls[-1][1]
    eq_args = [(c[1][0], str(c[1][1])) for c in chain if c[0] == "eq"]
    assert ("id", REPORT) in eq_args
    assert ("user_id", auth_user_id) in eq_args


def test_delete_research_404_when_notebook_not_owned(fake_supabase, app_client) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[])
    r = app_client.delete(f"/api/v1/notebooks/{NB}/research/{REPORT}")
    assert r.status_code == 404


def test_delete_research_404_cross_user(
    fake_supabase, app_client, auth_user_id
) -> None:
    """Notebook owned, but the report row does not exist for this user."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["research_reports"] = MagicMock(data=[])

    r = app_client.delete(f"/api/v1/notebooks/{NB}/research/{REPORT}")
    assert r.status_code == 404
