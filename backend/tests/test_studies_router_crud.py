"""T-TST-03: studies router upsert / list / get / delete + kind validation."""

from unittest.mock import MagicMock, patch

NB = "11111111-1111-1111-1111-111111111111"
SRC = "22222222-2222-2222-2222-222222222221"


def test_generate_flashcards_upserts(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["sources"] = MagicMock(
        data=[{"id": SRC, "name": "S"}]
    )
    fake_supabase.responses["source_chunks"] = MagicMock(
        data=[{"source_id": SRC, "content": "ctx text body", "chunk_index": 0}]
    )
    fake_supabase.responses["study_materials"] = MagicMock(
        data=[
            {
                "id": "66666666-6666-6666-6666-666666666661",
                "kind": "flashcards",
                "payload": {"flashcards": [{"q": "x", "a": "y"}]},
            }
        ]
    )

    import app.routers.studies as sm

    class _FastGemini:
        def generate_study_payload(self, *, kind, context):
            return (
                {"flashcards": [{"q": "x", "a": "y"}]},
                MagicMock(usage=MagicMock(cost_usd=0.0)),
            )

    with patch.object(sm, "get_gemini", lambda: _FastGemini()):
        r = app_client.post(f"/api/v1/notebooks/{NB}/studies/flashcards/generate")

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["data"]["kind"] == "flashcards"

    upserts = [
        c
        for c in fake_supabase.calls
        if c[0] == "study_materials" and any(op == "upsert" for (op, _, _) in c[1])
    ]
    assert upserts, "expected upsert on study_materials"
    # confirm on_conflict targets the unique constraint
    upsert_call = next(
        (op, args, kwargs)
        for (op, args, kwargs) in upserts[0][1]
        if op == "upsert"
    )
    assert upsert_call[2].get("on_conflict") == "notebook_id,kind"


def test_generate_no_ready_sources_returns_400(
    fake_supabase, app_client, auth_user_id
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["sources"] = MagicMock(data=[])

    r = app_client.post(f"/api/v1/notebooks/{NB}/studies/flashcards/generate")
    assert r.status_code == 400


def test_list_studies_returns_all_kinds(
    fake_supabase, app_client, auth_user_id
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["study_materials"] = MagicMock(
        data=[
            {"id": "sm-1", "kind": "flashcards", "payload": {}},
            {"id": "sm-2", "kind": "quiz", "payload": {}},
        ]
    )

    r = app_client.get(f"/api/v1/notebooks/{NB}/studies")
    assert r.status_code == 200
    rows = r.json()["data"]
    kinds = {row["kind"] for row in rows}
    assert "flashcards" in kinds and "quiz" in kinds


def test_list_studies_cross_user_returns_404(fake_supabase, app_client) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[])  # ownership fail

    r = app_client.get(f"/api/v1/notebooks/{NB}/studies")
    assert r.status_code == 404


def test_get_single_kind(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["study_materials"] = MagicMock(
        data=[{"id": "sm-1", "kind": "flashcards", "payload": {"flashcards": []}}]
    )

    r = app_client.get(f"/api/v1/notebooks/{NB}/studies/flashcards")
    assert r.status_code == 200
    assert r.json()["data"]["kind"] == "flashcards"


def test_get_single_kind_missing_returns_404(
    fake_supabase, app_client, auth_user_id
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["study_materials"] = MagicMock(data=[])

    r = app_client.get(f"/api/v1/notebooks/{NB}/studies/flashcards")
    assert r.status_code == 404


def test_delete_kind_204(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["study_materials"] = MagicMock(data=[])

    r = app_client.delete(f"/api/v1/notebooks/{NB}/studies/flashcards")
    assert r.status_code == 204

    deletes = [
        c
        for c in fake_supabase.calls
        if c[0] == "study_materials" and any(op == "delete" for (op, _, _) in c[1])
    ]
    assert deletes, "expected delete on study_materials"
    # confirm the delete is scoped by user_id (defense in depth)
    chain_ops = {op: (args, kwargs) for (op, args, kwargs) in deletes[0][1]}
    eq_calls = [c for c in deletes[0][1] if c[0] == "eq"]
    eq_fields = {args[0] for (_, args, _) in eq_calls}
    assert "user_id" in eq_fields
    assert "notebook_id" in eq_fields
    assert "kind" in eq_fields


def test_delete_kind_rejects_cross_user(fake_supabase, app_client) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[])  # ownership empty

    r = app_client.delete(f"/api/v1/notebooks/{NB}/studies/flashcards")
    assert r.status_code == 404


def test_generate_invalid_kind_returns_422(app_client) -> None:
    r = app_client.post(f"/api/v1/notebooks/{NB}/studies/not-a-kind/generate")
    assert r.status_code == 422


def test_get_invalid_kind_returns_422(app_client) -> None:
    r = app_client.get(f"/api/v1/notebooks/{NB}/studies/not-a-kind")
    assert r.status_code == 422


def test_delete_invalid_kind_returns_422(app_client) -> None:
    r = app_client.delete(f"/api/v1/notebooks/{NB}/studies/not-a-kind")
    assert r.status_code == 422
