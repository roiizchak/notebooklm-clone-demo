"""B-COR-05: studies generate must not block the worker on slow Gemini calls."""

from unittest.mock import MagicMock


def test_generate_study_returns_504_when_gemini_times_out(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[{"id": "11111111-1111-1111-1111-111111111111", "user_id": auth_user_id}])
    fake_supabase.responses["sources"] = MagicMock(data=[{"id": "22222222-2222-2222-2222-222222222221", "name": "S"}])
    fake_supabase.responses["source_chunks"] = MagicMock(
        data=[
            {
                "source_id": "22222222-2222-2222-2222-222222222221",
                "content": "lorem ipsum dolor sit amet",
                "chunk_index": 0,
            }
        ]
    )

    import app.routers.studies as studies_mod

    class _SlowGemini:
        def generate_study_payload(self, *, kind: str, context: str):
            import time
            time.sleep(2.0)
            return {"flashcards": [{"q": "x", "a": "y"}]}, MagicMock(usage=MagicMock(cost_usd=0.0))

    monkeypatch.setattr(studies_mod, "get_gemini", lambda: _SlowGemini())
    monkeypatch.setattr(studies_mod, "GEMINI_TIMEOUT_SECONDS", 0.2, raising=False)

    r = app_client.post("/api/v1/notebooks/11111111-1111-1111-1111-111111111111/studies/flashcards/generate")
    assert r.status_code == 504
    assert "timeout" in r.json()["detail"].lower() or "timed out" in r.json()["detail"].lower()


def test_generate_study_succeeds_under_timeout(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[{"id": "11111111-1111-1111-1111-111111111111", "user_id": auth_user_id}])
    fake_supabase.responses["sources"] = MagicMock(data=[{"id": "22222222-2222-2222-2222-222222222221", "name": "S"}])
    fake_supabase.responses["source_chunks"] = MagicMock(
        data=[
            {
                "source_id": "22222222-2222-2222-2222-222222222221",
                "content": "lorem ipsum dolor sit amet",
                "chunk_index": 0,
            }
        ]
    )
    fake_supabase.responses["study_materials"] = MagicMock(
        data=[{"id": "66666666-6666-6666-6666-666666666661", "kind": "flashcards", "payload": {"flashcards": [{"q": "x", "a": "y"}]}}]
    )

    import app.routers.studies as studies_mod

    class _FastGemini:
        def generate_study_payload(self, *, kind: str, context: str):
            return {"flashcards": [{"q": "x", "a": "y"}]}, MagicMock(usage=MagicMock(cost_usd=0.0))

    monkeypatch.setattr(studies_mod, "get_gemini", lambda: _FastGemini())

    r = app_client.post("/api/v1/notebooks/11111111-1111-1111-1111-111111111111/studies/flashcards/generate")
    assert r.status_code == 201
