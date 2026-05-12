def test_health(app_client) -> None:
    r = app_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy"}


def test_root(app_client) -> None:
    r = app_client.get("/")
    assert r.status_code == 200
    assert r.json()["docs"] == "/docs"
