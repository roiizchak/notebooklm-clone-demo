"""T-TST-01: sources router CRUD + ingest dispatch coverage.

Broad contract-level tests for `app.routers.sources`. Each test stays short
and pins one observable behaviour (status code + shape) rather than going
deep on internals. BackgroundTask callables are stubbed to no-ops so the
ingest pipeline never actually runs.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import app.routers.sources as sources_mod

NB = "11111111-1111-1111-1111-111111111111"
SRC = "22222222-2222-2222-2222-222222222221"


def _own(fake, auth_user_id: str) -> None:
    fake.responses["notebooks"] = MagicMock(data=[{"id": NB, "user_id": auth_user_id}])


def _stub_bg(monkeypatch) -> None:
    """No-op the BackgroundTask ingest entrypoints."""
    monkeypatch.setattr(
        sources_mod, "_ingest_and_finalize_with_rid", lambda *a, **kw: None
    )
    monkeypatch.setattr(sources_mod, "_ingest_and_finalize", lambda *a, **kw: None)


# ---------- text ----------


def test_create_text_source_202(fake_supabase, app_client, auth_user_id, monkeypatch) -> None:
    _own(fake_supabase, auth_user_id)
    fake_supabase.responses["sources"] = MagicMock(
        data=[{"id": SRC, "name": "t", "status": "processing"}]
    )
    _stub_bg(monkeypatch)

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/sources/text",
        json={"name": "t", "content": "hello world from the test"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["data"]["id"] == SRC
    assert body["data"]["status"] == "processing"


def test_create_text_source_rejects_empty_content(
    fake_supabase, app_client, auth_user_id
) -> None:
    _own(fake_supabase, auth_user_id)
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/sources/text",
        json={"name": "t", "content": ""},
    )
    assert r.status_code == 422, r.text


def test_create_text_source_unknown_notebook_404(fake_supabase, app_client) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(data=[])
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/sources/text",
        json={"name": "t", "content": "abc"},
    )
    assert r.status_code == 404, r.text


# ---------- url ----------


def test_create_url_source_202(fake_supabase, app_client, auth_user_id, monkeypatch) -> None:
    _own(fake_supabase, auth_user_id)
    fake_supabase.responses["sources"] = MagicMock(
        data=[{"id": SRC, "name": "https://example.com", "status": "processing"}]
    )
    _stub_bg(monkeypatch)

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/sources/url",
        json={"url": "https://example.com/article"},
    )
    assert r.status_code == 202, r.text
    assert r.json()["data"]["id"] == SRC


def test_url_source_rejects_non_url_payload(
    fake_supabase, app_client, auth_user_id
) -> None:
    _own(fake_supabase, auth_user_id)
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/sources/url",
        json={"url": "not-a-url"},
    )
    assert r.status_code == 422, r.text


# ---------- youtube ----------


def test_create_youtube_source_202(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    _own(fake_supabase, auth_user_id)
    fake_supabase.responses["sources"] = MagicMock(
        data=[{"id": SRC, "name": "video title", "status": "processing"}]
    )
    _stub_bg(monkeypatch)
    # Stub oEmbed to avoid network.
    monkeypatch.setattr(
        sources_mod, "_youtube_oembed", lambda url: {"title": "video title"}
    )

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/sources/youtube",
        json={"url": "https://www.youtube.com/watch?v=abc"},
    )
    assert r.status_code == 202, r.text
    assert r.json()["data"]["id"] == SRC


# ---------- upload-init ----------


def test_upload_init_returns_signed_url(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    _own(fake_supabase, auth_user_id)
    fake_supabase.responses["sources"] = MagicMock(
        data=[{"id": SRC, "status": "pending"}]
    )
    monkeypatch.setattr(
        sources_mod,
        "create_signed_upload_url",
        lambda b, p: {"signed_url": "https://stub/sign", "token": "tok", "path": p},
    )

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/sources/upload-init",
        json={
            "filename": "doc.pdf",
            "mime_type": "application/pdf",
            "size": 1024,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["source_id"] == SRC
    assert data["signed_url"] == "https://stub/sign"
    assert data["token"] == "tok"
    assert data["expires_in"] == 600
    assert data["storage_path"].endswith("/doc.pdf")


def test_upload_init_rejects_oversize(
    fake_supabase, app_client, auth_user_id
) -> None:
    _own(fake_supabase, auth_user_id)
    # Pydantic caps `size` at 50 MiB → 422 from request validation.
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/sources/upload-init",
        json={
            "filename": "huge.pdf",
            "mime_type": "application/pdf",
            "size": 100 * 1024 * 1024,
        },
    )
    assert r.status_code in (400, 413, 422), r.text


def test_upload_init_rejects_unsupported_mime(
    fake_supabase, app_client, auth_user_id
) -> None:
    _own(fake_supabase, auth_user_id)
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/sources/upload-init",
        json={
            "filename": "image.png",
            "mime_type": "image/png",
            "size": 1024,
        },
    )
    assert r.status_code == 415, r.text


# ---------- upload-complete ----------


def test_upload_complete_404_when_missing(
    fake_supabase, app_client, auth_user_id
) -> None:
    _own(fake_supabase, auth_user_id)
    fake_supabase.responses["sources"] = MagicMock(data=[])
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/sources/upload-complete",
        json={"source_id": SRC},
    )
    assert r.status_code == 404, r.text


def test_upload_complete_400_without_storage_path(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    _own(fake_supabase, auth_user_id)
    fake_supabase.responses["sources"] = MagicMock(
        data=[
            {
                "id": SRC,
                "notebook_id": NB,
                "status": "pending",
                "type": "pdf",
                "file_path": None,
            }
        ]
    )
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/sources/upload-complete",
        json={"source_id": SRC},
    )
    assert r.status_code == 400, r.text


def test_upload_complete_202_when_object_present(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    _own(fake_supabase, auth_user_id)
    fake_supabase.responses["sources"] = MagicMock(
        data=[
            {
                "id": SRC,
                "notebook_id": NB,
                "status": "pending",
                "type": "pdf",
                "name": "doc.pdf",
                "file_path": "u/n/s/doc.pdf",
                "original_filename": "doc.pdf",
                "mime_type": "application/pdf",
                "file_size_bytes": 1024,
            }
        ]
    )
    monkeypatch.setattr(sources_mod, "object_exists", lambda b, p: True)
    _stub_bg(monkeypatch)

    r = app_client.post(
        f"/api/v1/notebooks/{NB}/sources/upload-complete",
        json={"source_id": SRC},
    )
    assert r.status_code == 202, r.text
    assert r.json()["data"]["status"] == "processing"


def test_upload_complete_idempotent_for_processing_row(
    fake_supabase, app_client, auth_user_id
) -> None:
    _own(fake_supabase, auth_user_id)
    fake_supabase.responses["sources"] = MagicMock(
        data=[
            {
                "id": SRC,
                "notebook_id": NB,
                "status": "processing",
                "type": "pdf",
                "file_path": "u/n/s/x.pdf",
            }
        ]
    )
    r = app_client.post(
        f"/api/v1/notebooks/{NB}/sources/upload-complete",
        json={"source_id": SRC},
    )
    assert r.status_code == 202, r.text
    assert r.json()["data"]["status"] == "processing"


# ---------- list / get / delete ----------


def test_list_sources_returns_data_array(
    fake_supabase, app_client, auth_user_id
) -> None:
    _own(fake_supabase, auth_user_id)
    fake_supabase.responses["sources"] = MagicMock(
        data=[{"id": SRC, "name": "s", "status": "ready"}]
    )
    r = app_client.get(f"/api/v1/notebooks/{NB}/sources?limit=10&offset=5")
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["data"], list)


def test_list_sources_rejects_bad_limit(
    fake_supabase, app_client, auth_user_id
) -> None:
    _own(fake_supabase, auth_user_id)
    r = app_client.get(f"/api/v1/notebooks/{NB}/sources?limit=9999")
    assert r.status_code == 422, r.text


def test_get_source_404(fake_supabase, app_client, auth_user_id) -> None:
    _own(fake_supabase, auth_user_id)
    fake_supabase.responses["sources"] = MagicMock(data=[])
    r = app_client.get(f"/api/v1/notebooks/{NB}/sources/{SRC}")
    assert r.status_code == 404, r.text


def test_get_source_returns_row(fake_supabase, app_client, auth_user_id) -> None:
    _own(fake_supabase, auth_user_id)
    fake_supabase.responses["sources"] = MagicMock(
        data=[{"id": SRC, "name": "x", "status": "ready"}]
    )
    r = app_client.get(f"/api/v1/notebooks/{NB}/sources/{SRC}")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["id"] == SRC


def test_delete_source_204(fake_supabase, app_client, auth_user_id) -> None:
    _own(fake_supabase, auth_user_id)
    fake_supabase.responses["sources"] = MagicMock(
        data=[{"file_path": None}]
    )
    r = app_client.delete(f"/api/v1/notebooks/{NB}/sources/{SRC}")
    assert r.status_code == 204, r.text


def test_delete_source_rejects_cross_user(fake_supabase, app_client) -> None:
    # Ownership lookup returns empty → 404 before the sources query runs.
    fake_supabase.responses["notebooks"] = MagicMock(data=[])
    r = app_client.delete(f"/api/v1/notebooks/{NB}/sources/{SRC}")
    assert r.status_code == 404, r.text


def test_delete_source_404_when_source_missing(
    fake_supabase, app_client, auth_user_id
) -> None:
    _own(fake_supabase, auth_user_id)
    fake_supabase.responses["sources"] = MagicMock(data=[])
    r = app_client.delete(f"/api/v1/notebooks/{NB}/sources/{SRC}")
    assert r.status_code == 404, r.text


# ---------- UUID path validation ----------


def test_text_source_invalid_uuid_path_422(app_client) -> None:
    r = app_client.post(
        "/api/v1/notebooks/not-a-uuid/sources/text",
        json={"name": "t", "content": "abc"},
    )
    assert r.status_code == 422, r.text
