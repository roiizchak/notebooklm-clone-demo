"""B-COR-03: upload-init must sweep stale pending rows before issuing a new one."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


def test_upload_init_deletes_stale_pending_rows(
    fake_supabase, app_client, auth_user_id, monkeypatch
) -> None:
    fake_supabase.responses["notebooks"] = MagicMock(
        data=[{"id": "11111111-1111-1111-1111-111111111111", "user_id": auth_user_id}]
    )
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    state = {"calls": 0}

    def _sources_response(chain):
        state["calls"] += 1
        # 1st call: select stale pending rows.
        if state["calls"] == 1:
            return [
                {"id": "stale-a", "file_path": "u/n/stale-a/x.pdf", "created_at": stale_ts},
                {"id": "stale-b", "file_path": "u/n/stale-b/y.pdf", "created_at": stale_ts},
            ]
        # 2nd call: delete-by-id (returns the deleted ids).
        if state["calls"] == 2:
            return []
        # 3rd call: insert new row.
        if state["calls"] == 3:
            return [
                {
                    "id": "src-new",
                    "notebook_id": "11111111-1111-1111-1111-111111111111",
                    "type": "pdf",
                    "name": "doc.pdf",
                    "status": "pending",
                }
            ]
        # 4th+: update file_path on the new row.
        return [{}]

    fake_supabase.responses["sources"] = _sources_response

    # Stub out the storage helper to avoid real Supabase calls.
    import app.routers.sources as sources_mod

    monkeypatch.setattr(
        sources_mod,
        "create_signed_upload_url",
        lambda b, p: {"signed_url": "https://signed/x", "token": "tok", "path": p},
    )

    r = app_client.post(
        "/api/v1/notebooks/11111111-1111-1111-1111-111111111111/sources/upload-init",
        json={"filename": "doc.pdf", "mime_type": "application/pdf", "size": 1024},
    )
    assert r.status_code == 201, r.text
    sources_chains = [chain for (t, chain) in fake_supabase.calls if t == "sources"]
    assert any(
        any(c[0] == "delete" for c in chain) for chain in sources_chains
    ), "expected a delete on sources during sweep"
