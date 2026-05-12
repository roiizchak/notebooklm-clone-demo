"""B-COR-02: simultaneous audio generations must not stack."""

from unittest.mock import MagicMock


def _owned_notebook(user_id: str) -> dict:
    return {"id": "00000000-0000-0000-0000-0000000000b1", "user_id": user_id}


def test_generate_audio_returns_409_when_active_row_exists(
    fake_supabase, app_client, auth_user_id
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["audio_overviews"] = MagicMock(
        data=[{"id": "33333333-3333-3333-3333-333333333331", "status": "pending", "notebook_id": "00000000-0000-0000-0000-0000000000b1", "user_id": auth_user_id}]
    )

    r = app_client.post(
        "/api/v1/notebooks/00000000-0000-0000-0000-0000000000b1/audio/generate", json={"target_minutes": 5}
    )
    assert r.status_code == 409
    assert "already" in r.json()["detail"].lower()


def test_generate_audio_proceeds_when_no_active_row(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    state = {"calls": 0}

    def _audio_response(chain):
        state["calls"] += 1
        # 1st call = SELECT for dedup; subsequent calls = INSERT.
        if state["calls"] == 1:
            return []
        return [{"id": "audio-new", "status": "pending"}]

    fake_supabase.responses["audio_overviews"] = _audio_response

    # Stub out the BackgroundTask runner — we don't need real generation.
    import app.routers.audio as audio_mod
    monkeypatch.setattr(audio_mod, "run_audio_generation_blocking", lambda _id: None)

    r = app_client.post(
        "/api/v1/notebooks/00000000-0000-0000-0000-0000000000b1/audio/generate", json={"target_minutes": 5}
    )
    assert r.status_code == 202
    assert r.json()["data"]["status"] == "pending"
