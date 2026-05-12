"""T-TST-04: notes CRUD + pin + saved-from-chat + cross-user isolation."""

from __future__ import annotations

from unittest.mock import MagicMock

NB = "11111111-1111-1111-1111-111111111111"
NOTE = "55555555-5555-5555-5555-555555555551"
MSG = "77777777-7777-7777-7777-777777777771"
SESSION = "44444444-4444-4444-4444-444444444441"


def test_create_written_note(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["notes"] = MagicMock(
        data=[
            {
                "id": NOTE,
                "notebook_id": NB,
                "user_id": auth_user_id,
                "type": "written",
                "title": None,
                "content": "x",
                "tags": [],
                "is_pinned": False,
                "original_message_id": None,
            }
        ]
    )
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/notes",
        json={"type": "written", "content": "x"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["id"] == NOTE


def test_create_written_note_rejects_original_message_id(
    fake_supabase, app_client, auth_user_id
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/notes",
        json={"type": "written", "content": "x", "original_message_id": MSG},
    )
    assert r.status_code == 400, r.text


def test_create_saved_response_note(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    # _verify_chat_message_in_notebook returns the joined row directly.
    # Real Supabase serialises FK columns as strings; the router casts the
    # path-param UUID to str before comparing (notes.py:create_note).
    fake_supabase.responses["chat_messages"] = MagicMock(
        data=[
            {
                "id": MSG,
                "session_id": SESSION,
                "chat_sessions": {"notebook_id": NB},
            }
        ]
    )
    fake_supabase.responses["notes"] = MagicMock(
        data=[
            {
                "id": NOTE,
                "notebook_id": NB,
                "user_id": auth_user_id,
                "type": "saved_response",
                "content": "saved-text",
                "is_pinned": False,
                "original_message_id": MSG,
            }
        ]
    )
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/notes",
        json={
            "type": "saved_response",
            "content": "saved-text",
            "original_message_id": MSG,
        },
    )
    assert r.status_code == 201, r.text


def test_create_saved_response_for_research_message(
    fake_supabase, app_client, auth_user_id
) -> None:
    """Regression: research-mode assistant messages must be save-to-notes-able.

    Pre-fix, ``UUID(NB) != "NB"`` always fired the 'does not belong' branch.
    Pins the str(notebook_id) cast at the top of create_note.
    """
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["chat_messages"] = MagicMock(
        data=[
            {
                "id": MSG,
                "session_id": SESSION,
                # Real Supabase returns this column as a string.
                "chat_sessions": {"notebook_id": NB},
            }
        ]
    )
    fake_supabase.responses["notes"] = MagicMock(
        data=[
            {
                "id": NOTE,
                "notebook_id": NB,
                "user_id": auth_user_id,
                "type": "saved_response",
                "content": "## TL;DR\n\nResearch body...",
                "is_pinned": False,
                "original_message_id": MSG,
            }
        ]
    )
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/notes",
        json={
            "type": "saved_response",
            "title": "Saved research",
            "content": "## TL;DR\n\nResearch body...",
            "original_message_id": MSG,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["original_message_id"] == MSG


def test_create_saved_response_requires_original_message_id(
    fake_supabase, app_client, auth_user_id
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/notes",
        json={"type": "saved_response", "content": "x"},
    )
    assert r.status_code == 400, r.text


def test_create_saved_response_rejects_message_in_other_notebook(
    fake_supabase, app_client, auth_user_id
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    # Message exists but is in a different notebook.
    other_nb = "22222222-2222-2222-2222-222222222222"
    fake_supabase.responses["chat_messages"] = MagicMock(
        data=[
            {
                "id": MSG,
                "session_id": SESSION,
                "chat_sessions": {"notebook_id": other_nb},
            }
        ]
    )
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/notes",
        json={
            "type": "saved_response",
            "content": "x",
            "original_message_id": MSG,
        },
    )
    assert r.status_code == 400, r.text


def test_create_note_rejects_unowned_notebook(fake_supabase, app_client) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[])
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/notes",
        json={"type": "written", "content": "x"},
    )
    assert r.status_code == 404


def test_list_notes(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["notes"] = MagicMock(
        data=[
            {"id": "n1", "is_pinned": True, "content": "p"},
            {"id": "n2", "is_pinned": False, "content": "u"},
        ]
    )
    r = app_client.get(f"/api/v1/notebooks/{NB}/notes")
    assert r.status_code == 200
    assert len(r.json()["data"]) == 2


def test_list_notes_applies_pagination(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["notes"] = MagicMock(data=[])
    r = app_client.get(f"/api/v1/notebooks/{NB}/notes?limit=10&offset=20")
    assert r.status_code == 200
    # Verify the chain recorded the limit / range call.
    notes_calls = [c for c in fake_supabase.calls if c[0] == "notes"]
    assert notes_calls, "expected a notes table call"
    chain_methods = [step[0] for step in notes_calls[-1][1]]
    assert "limit" in chain_methods
    assert "range" in chain_methods


def test_get_single_note(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["notes"] = MagicMock(
        data=[{"id": NOTE, "content": "x", "is_pinned": False}]
    )
    r = app_client.get(f"/api/v1/notebooks/{NB}/notes/{NOTE}")
    assert r.status_code == 200
    assert r.json()["data"]["id"] == NOTE


def test_get_note_404_when_missing(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["notes"] = MagicMock(data=[])
    r = app_client.get(f"/api/v1/notebooks/{NB}/notes/{NOTE}")
    assert r.status_code == 404


def test_patch_note_content(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["notes"] = MagicMock(
        data=[{"id": NOTE, "content": "updated", "is_pinned": False}]
    )
    r = app_client.patch(
        f"/api/v1/notebooks/{NB}/notes/{NOTE}",
        json={"content": "updated"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["content"] == "updated"


def test_pin_note(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["notes"] = MagicMock(
        data=[{"id": NOTE, "content": "x", "is_pinned": True}]
    )
    r = app_client.patch(
        f"/api/v1/notebooks/{NB}/notes/{NOTE}",
        json={"is_pinned": True},
    )
    assert r.status_code == 200
    assert r.json()["data"]["is_pinned"] is True


def test_patch_empty_body_rejected(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    # Note exists (so we get past _get_owned_note_or_404).
    fake_supabase.responses["notes"] = MagicMock(
        data=[{"id": NOTE, "content": "x", "is_pinned": False}]
    )
    r = app_client.patch(f"/api/v1/notebooks/{NB}/notes/{NOTE}", json={})
    assert r.status_code == 400


def test_delete_note(fake_supabase, app_client, auth_user_id) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": NB, "user_id": auth_user_id}]
    )
    fake_supabase.responses["notes"] = MagicMock(
        data=[{"id": NOTE, "content": "x", "is_pinned": False}]
    )
    r = app_client.delete(f"/api/v1/notebooks/{NB}/notes/{NOTE}")
    assert r.status_code == 204


def test_delete_note_rejects_cross_user(fake_supabase, app_client) -> None:
    # Ownership check returns empty → 404 before touching notes.
    fake_supabase.responses["notebooks"] = MagicMock(data=[])
    r = app_client.delete(f"/api/v1/notebooks/{NB}/notes/{NOTE}")
    assert r.status_code == 404
