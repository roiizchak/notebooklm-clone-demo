"""P-PRF-03: list_sources and list_notes accept ?limit= and ?offset= with sane defaults."""

from unittest.mock import MagicMock

NB = "11111111-1111-1111-1111-111111111111"


def test_list_sources_default_caps_at_50(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[{"id": NB, "user_id": auth_user_id}])
    fake_supabase.responses["sources"] = MagicMock(data=[])

    r = app_client.get(f"/api/v1/notebooks/{NB}/sources")
    assert r.status_code == 200
    calls = [c for c in fake_supabase.calls if c[0] == "sources"]
    assert calls
    chain = calls[-1][1]
    limit_call = [args for (op, args, _) in chain if op == "limit"]
    assert limit_call, f"expected .limit on sources query, got ops {[op for (op, _, _) in chain]}"
    assert limit_call[0][0] == 50


def test_list_sources_accepts_query_params(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[{"id": NB, "user_id": auth_user_id}])
    fake_supabase.responses["sources"] = MagicMock(data=[])

    r = app_client.get(f"/api/v1/notebooks/{NB}/sources?limit=10&offset=5")
    assert r.status_code == 200
    chain = [c for c in fake_supabase.calls if c[0] == "sources"][-1][1]
    limit_call = [args for (op, args, _) in chain if op == "limit"]
    range_call = [args for (op, args, _) in chain if op == "range"]
    assert limit_call[0][0] == 10
    assert range_call, "expected .range(offset, offset+limit-1) for offset support"


def test_list_notes_default_caps_at_50(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[{"id": NB, "user_id": auth_user_id}])
    fake_supabase.responses["notes"] = MagicMock(data=[])

    r = app_client.get(f"/api/v1/notebooks/{NB}/notes")
    assert r.status_code == 200
    chain = [c for c in fake_supabase.calls if c[0] == "notes"][-1][1]
    limit_call = [args for (op, args, _) in chain if op == "limit"]
    assert limit_call and limit_call[0][0] == 50
