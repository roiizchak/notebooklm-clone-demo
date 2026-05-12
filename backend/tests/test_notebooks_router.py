"""Notebooks CRUD router tests using the FakeSupabase."""

from unittest.mock import MagicMock

import pytest


def _set_notebook_response(fake, *, found: bool = True, user_id: str = "00000000-0000-0000-0000-000000000001"):
    """Helper: returns owned-notebook row or empty."""
    nb = {
        "id": "11111111-1111-1111-1111-111111111111",
        "user_id": user_id,
        "name": "Sample",
        "description": None,
        "emoji": "📓",
        "settings": {},
        "source_count": 0,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    fake.responses["notebooks"] = MagicMock(data=[nb] if found else [])


def test_create_notebook_inserts_with_user_id(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[
            {
                "id": "nb-new",
                "user_id": auth_user_id,
                "name": "Q4",
                "description": None,
                "emoji": "📊",
                "settings": {},
                "source_count": 0,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ]
    )
    r = app_client.post("/api/v1/notebooks", json={"name": "Q4", "emoji": "📊"})
    assert r.status_code == 201
    assert r.json()["data"]["name"] == "Q4"

    # Verify user_id was attached on insert.
    last_call_chain = fake_supabase.calls[-1][1]
    assert any(
        call[0] == "insert" and call[1][0]["user_id"] == auth_user_id
        for call in last_call_chain
    )


def test_get_notebook_404_when_not_owned(fake_supabase, app_client) -> None:
    _set_notebook_response(fake_supabase, found=False)
    r = app_client.get("/api/v1/notebooks/99999999-9999-9999-9999-999999999999")
    assert r.status_code == 404


def test_get_notebook_returns_data(fake_supabase, app_client, auth_user_id) -> None:
    _set_notebook_response(fake_supabase, found=True, user_id=auth_user_id)
    r = app_client.get("/api/v1/notebooks/11111111-1111-1111-1111-111111111111")
    assert r.status_code == 200
    assert r.json()["data"]["id"] == "11111111-1111-1111-1111-111111111111"


def test_list_notebooks(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[
            {
                "id": "a",
                "user_id": auth_user_id,
                "name": "A",
                "description": None,
                "emoji": "📓",
                "settings": {},
                "source_count": 0,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ]
    )
    r = app_client.get("/api/v1/notebooks")
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1


def test_create_notebook_requires_auth() -> None:
    """Without dependency override, the endpoint should 401."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    r = client.post("/api/v1/notebooks", json={"name": "X"})
    assert r.status_code == 401
