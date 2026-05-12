"""Regression: UUID path params must not enter Supabase insert/upsert payloads
as raw UUID objects -- httpx can't JSON-serialise them.

Task 1 of the quality plan converted FastAPI path params from str to UUID.
Without explicit `str(notebook_id)` conversion at insert/upsert call sites,
the supabase-py client serialises the body via httpx.json which raises
`TypeError: Object of type UUID is not JSON serializable` (production-confirmed
on POST /studies/{kind}/generate, May 2026).

This module asserts JSON-cleanliness of every insert/upsert/update payload
captured by FakeSupabase for each Phase 2 write path.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4


def _assert_no_raw_uuid_in_value(value: Any, path: str = "") -> None:
    """Recursively assert no raw UUID instances anywhere in a structure."""
    assert not isinstance(value, UUID), (
        f"raw UUID found at {path or '<root>'}: {value!r}"
    )
    if isinstance(value, dict):
        for k, v in value.items():
            _assert_no_raw_uuid_in_value(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _assert_no_raw_uuid_in_value(v, f"{path}[{i}]")


def _assert_calls_clean(fake_supabase) -> None:
    """All recorded insert/upsert/update payload dicts must be JSON-serialisable
    and contain no raw UUID instances."""
    write_ops = ("insert", "upsert", "update")
    for table, chain in fake_supabase.calls:
        for op, args, kwargs in chain:
            if op not in write_ops:
                continue
            for arg in args:
                if isinstance(arg, (dict, list)):
                    _assert_no_raw_uuid_in_value(arg, f"{table}.{op}.args")
                    try:
                        json.dumps(arg)
                    except TypeError as e:
                        raise AssertionError(
                            f"non-JSON-serialisable in {table}.{op}: {arg!r} ({e})"
                        ) from None
            for k, v in kwargs.items():
                if isinstance(v, (dict, list)):
                    _assert_no_raw_uuid_in_value(v, f"{table}.{op}.{k}")
                    try:
                        json.dumps(v)
                    except TypeError as e:
                        raise AssertionError(
                            f"non-JSON-serialisable in {table}.{op}.{k}: {v!r} ({e})"
                        ) from None


# ---------- studies (the path that actually exploded in prod) ----------


def test_studies_generate_payload_has_no_raw_uuid(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    nb = str(uuid4())
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": nb, "user_id": auth_user_id}]
    )
    fake_supabase.responses["sources"] = MagicMock(
        data=[{"id": "s1", "name": "S", "status": "ready"}]
    )
    fake_supabase.responses["source_chunks"] = MagicMock(
        data=[{"source_id": "s1", "content": "ctx", "chunk_index": 0}]
    )
    fake_supabase.responses["study_materials"] = MagicMock(
        data=[
            {
                "id": "sm-1",
                "kind": "flashcards",
                "payload": {"flashcards": [{"q": "x", "a": "y"}]},
            }
        ]
    )

    import app.routers.studies as sm

    class _Usage:
        cost_usd = 0.0
        model_used = "g"
        input_tokens = 1
        output_tokens = 1

    class _Chat:
        usage = _Usage()

    class _FastGemini:
        def generate_study_payload(self, *, kind, context):
            return ({"flashcards": [{"q": "x", "a": "y"}]}, _Chat())

    monkeypatch.setattr(sm, "get_gemini", lambda: _FastGemini())

    r = app_client.post(f"/api/v1/notebooks/{nb}/studies/flashcards/generate")
    assert r.status_code == 201, r.text
    _assert_calls_clean(fake_supabase)


# ---------- notes (insert path takes UUID notebook_id + optional UUID body field) ----------


def test_notes_create_written_payload_has_no_raw_uuid(
    fake_supabase, app_client, auth_user_id
) -> None:
    nb = str(uuid4())
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": nb, "user_id": auth_user_id}]
    )
    fake_supabase.responses["notes"] = MagicMock(
        data=[{"id": "n1", "type": "written", "content": "hi"}]
    )

    r = app_client.post(
        f"/api/v1/notebooks/{nb}/notes",
        json={"type": "written", "content": "hi"},
    )
    assert r.status_code == 201, r.text
    _assert_calls_clean(fake_supabase)


# ---------- sources ----------


def test_sources_text_create_payload_has_no_raw_uuid(
    fake_supabase, app_client, auth_user_id
) -> None:
    nb = str(uuid4())
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": nb, "user_id": auth_user_id}]
    )
    fake_supabase.responses["sources"] = MagicMock(
        data=[{"id": "src-1", "status": "processing", "type": "text", "name": "n"}]
    )

    r = app_client.post(
        f"/api/v1/notebooks/{nb}/sources/text",
        json={"name": "scratch", "content": "hello world"},
    )
    assert r.status_code == 202, r.text
    _assert_calls_clean(fake_supabase)


# ---------- chat (insert into chat_sessions + chat_messages) ----------


def test_chat_send_message_payload_has_no_raw_uuid(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    nb = str(uuid4())
    sess_id = str(uuid4())
    msg_id = str(uuid4())

    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": nb, "user_id": auth_user_id}]
    )
    # _get_session_or_create insert returns a session row.
    fake_supabase.responses["chat_sessions"] = MagicMock(
        data=[{"id": sess_id, "notebook_id": nb, "title": None}]
    )
    fake_supabase.responses["chat_messages"] = MagicMock(
        data=[
            {
                "id": msg_id,
                "session_id": sess_id,
                "role": "assistant",
                "content": "hello",
            }
        ]
    )

    import app.routers.chat as chat_mod

    class _Usage:
        model_used = "g"
        input_tokens = 1
        output_tokens = 1
        cost_usd = 0.0

    class _Answer:
        content = "hello"
        citations: list = []
        source_ids_used: list = []
        chat_usage = _Usage()
        embed_usage = _Usage()

    async def _fake_answer(**kwargs):
        return _Answer()

    monkeypatch.setattr(chat_mod.rag, "answer", _fake_answer)
    # Block the background _backfill_session_title task -- it would otherwise
    # call Gemini (returning a MagicMock title) and write that into chat_sessions.
    monkeypatch.setattr(chat_mod, "_backfill_session_title", lambda *a, **kw: None)

    r = app_client.post(
        f"/api/v1/notebooks/{nb}/chat",
        json={"message": "hi"},
    )
    assert r.status_code == 200, r.text
    _assert_calls_clean(fake_supabase)
