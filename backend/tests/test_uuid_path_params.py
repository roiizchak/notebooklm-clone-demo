"""B-COR-07: path params declared as UUID return 422 on malformed input."""

import pytest

# A valid UUID for the notebook part of the chat-session path, so the bad
# segment under test is unambiguously the session_id UUID.
_NB = "00000000-0000-0000-0000-0000000000aa"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/notebooks/not-a-uuid",
        "/api/v1/notebooks/not-a-uuid/sources",
        "/api/v1/notebooks/not-a-uuid/audio",
        "/api/v1/notebooks/not-a-uuid/notes",
        "/api/v1/notebooks/not-a-uuid/studies",
        f"/api/v1/notebooks/{_NB}/chat/sessions/not-a-uuid",
    ],
)
def test_malformed_uuid_returns_422(app_client, path: str) -> None:
    r = app_client.get(path)
    assert r.status_code == 422, f"expected 422 for {path}, got {r.status_code}"
