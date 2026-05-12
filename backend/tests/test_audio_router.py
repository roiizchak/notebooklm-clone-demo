"""T-TST-02 router: audio overview generate / list / url / delete."""

from unittest.mock import MagicMock

NB = "11111111-1111-1111-1111-111111111111"
AUDIO = "33333333-3333-3333-3333-333333333331"


def _owned_notebook(user_id: str) -> dict:
    return {"id": NB, "user_id": user_id}


def test_generate_returns_202_and_schedules_task(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    """POST /generate with no active row returns 202 + pending row id."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])

    state = {"calls": 0}

    def _audio_response(chain):
        state["calls"] += 1
        # 1st call = SELECT for in-flight dedup; 2nd = INSERT.
        if state["calls"] == 1:
            return []
        return [{"id": AUDIO, "status": "pending"}]

    fake_supabase.responses["audio_overviews"] = _audio_response

    # Capture the scheduled BackgroundTask without executing it.
    scheduled: list[str] = []
    import app.routers.audio as audio_mod

    def _capture(_id: str) -> None:
        scheduled.append(_id)

    monkeypatch.setattr(audio_mod, "run_audio_generation_blocking", _capture)

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/audio/generate",
        json={"target_minutes": 5},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["data"]["id"] == AUDIO
    assert body["data"]["status"] == "pending"
    # The BackgroundTask runs after the response body is sent — TestClient
    # flushes it synchronously, so the capture list is populated.
    assert scheduled == [AUDIO]


def test_generate_rejects_invalid_target_minutes(
    fake_supabase, app_client, auth_user_id
) -> None:
    """target_minutes other than 5/10/15 is rejected (schema enforces this)."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/audio/generate",
        json={"target_minutes": 7},
    )
    # Pydantic Literal validation -> 422.
    assert r.status_code == 422


def test_list_audio_filters_to_notebook(
    fake_supabase, app_client, auth_user_id
) -> None:
    """GET /audio returns rows filtered to the requested notebook."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["audio_overviews"] = MagicMock(
        data=[
            {"id": AUDIO, "notebook_id": NB, "status": "ready"},
            {"id": "33333333-3333-3333-3333-333333333332", "notebook_id": NB, "status": "failed"},
        ]
    )

    r = app_client.get(f"/api/v1/notebooks/{NB}/audio")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == 2
    assert {row["id"] for row in rows} == {AUDIO, "33333333-3333-3333-3333-333333333332"}

    # Verify the table chain included .eq("notebook_id", NB) and .eq("user_id", ...).
    audio_calls = [c for c in fake_supabase.calls if c[0] == "audio_overviews"]
    assert audio_calls, "expected a select against audio_overviews"
    chain = audio_calls[-1][1]
    # Path params arrive as UUID instances; user_id stays str.
    eq_args = [(c[1][0], str(c[1][1])) for c in chain if c[0] == "eq"]
    assert ("notebook_id", NB) in eq_args
    assert ("user_id", auth_user_id) in eq_args


def test_get_audio_url_returns_signed_url_when_ready(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    """GET /audio/{id}/url returns a 10-min signed download URL for ready audio."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["audio_overviews"] = MagicMock(
        data=[
            {
                "id": AUDIO,
                "notebook_id": NB,
                "user_id": auth_user_id,
                "status": "ready",
                "audio_path": f"{auth_user_id}/{NB}/{AUDIO}.wav",
            }
        ]
    )

    # The router calls storage.create_signed_download_url() — patch at the
    # router-import site rather than relying on the storage helper to call
    # the fake supabase client.
    import app.routers.audio as audio_mod

    monkeypatch.setattr(
        audio_mod,
        "create_signed_download_url",
        lambda bucket, path, expires_in: "https://stub.supabase.co/dl?token=abc",
    )

    r = app_client.get(f"/api/v1/notebooks/{NB}/audio/{AUDIO}/url")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["signed_url"] == "https://stub.supabase.co/dl?token=abc"
    assert body["expires_in"] == 600


def test_get_audio_url_409_when_not_ready(
    fake_supabase, app_client, auth_user_id
) -> None:
    """Cannot fetch URL while still generating."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["audio_overviews"] = MagicMock(
        data=[
            {
                "id": AUDIO,
                "notebook_id": NB,
                "user_id": auth_user_id,
                "status": "generating",
                "audio_path": None,
            }
        ]
    )

    r = app_client.get(f"/api/v1/notebooks/{NB}/audio/{AUDIO}/url")
    assert r.status_code == 409
    assert "not ready" in r.json()["detail"].lower()


def test_delete_audio_rejects_when_notebook_not_owned(
    fake_supabase, app_client
) -> None:
    """Notebook ownership empty -> 404 before any audio_overviews delete."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[])
    r = app_client.delete(f"/api/v1/notebooks/{NB}/audio/{AUDIO}")
    assert r.status_code == 404


def test_delete_audio_succeeds_for_owner(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    """Owner can delete: notebook lookup OK + audio row found -> 204."""
    fake_supabase.responses["notebooks"] = MagicMock(data=[_owned_notebook(auth_user_id)])
    fake_supabase.responses["audio_overviews"] = MagicMock(
        data=[
            {
                "id": AUDIO,
                "notebook_id": NB,
                "user_id": auth_user_id,
                "status": "ready",
                "audio_path": f"{auth_user_id}/{NB}/{AUDIO}.wav",
            }
        ]
    )

    deleted: list[tuple[str, str]] = []
    import app.routers.audio as audio_mod

    monkeypatch.setattr(
        audio_mod,
        "delete_object",
        lambda bucket, path: deleted.append((bucket, path)),
    )

    r = app_client.delete(f"/api/v1/notebooks/{NB}/audio/{AUDIO}")
    assert r.status_code == 204
    # Storage delete is best-effort: confirm it was attempted with right bucket.
    assert deleted == [("audio", f"{auth_user_id}/{NB}/{AUDIO}.wav")]

    # And confirm the DB delete was scoped to (id, user_id).
    delete_calls = [
        c for c in fake_supabase.calls
        if c[0] == "audio_overviews" and any(op == "delete" for (op, _, _) in c[1])
    ]
    assert delete_calls, "expected a delete on audio_overviews"
    chain = delete_calls[-1][1]
    eq_args = [(c[1][0], str(c[1][1])) for c in chain if c[0] == "eq"]
    assert ("id", AUDIO) in eq_args
    assert ("user_id", auth_user_id) in eq_args
