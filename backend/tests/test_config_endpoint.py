"""F-UX-26: GET /api/v1/config returns max_file_bytes."""


def test_config_endpoint_returns_max_file_bytes(app_client) -> None:
    r = app_client.get("/api/v1/config")
    assert r.status_code == 200
    body = r.json()
    assert body["max_file_bytes"] == 50 * 1024 * 1024


def test_config_endpoint_is_unauthenticated(app_client) -> None:
    # No auth header — should still return 200.
    r = app_client.get("/api/v1/config")
    assert r.status_code == 200
