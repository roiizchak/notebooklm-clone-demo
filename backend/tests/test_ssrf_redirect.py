"""F3: extract_url must re-validate every redirect hop against the SSRF guard."""

from __future__ import annotations

import socket

import pytest

from app.services import ingestion


class _FakeResp:
    def __init__(self, *, is_redirect: bool, location: str | None = None, text: str = "") -> None:
        self.is_redirect = is_redirect
        self.headers = {"location": location} if location else {}
        self.text = text
        self.url = "https://example.com/"

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """Returns queued responses in order for successive .get() calls."""

    def __init__(self, responses: list[_FakeResp]) -> None:
        self._responses = responses
        self._i = 0

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *a) -> None:
        return None

    def get(self, url, headers=None):  # noqa: ANN001
        resp = self._responses[self._i]
        self._i += 1
        return resp


def _resolver(mapping: dict[str, str]):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        ip = mapping.get(host, "93.184.216.34")  # default public
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return fake_getaddrinfo


def test_redirect_to_private_host_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", _resolver({"example.com": "93.184.216.34", "internal.attacker": "10.0.0.5"})
    )
    # First GET on the public URL 302s to a private host.
    responses = [_FakeResp(is_redirect=True, location="http://internal.attacker/")]
    monkeypatch.setattr(ingestion.httpx, "Client", lambda **kw: _FakeClient(responses))

    with pytest.raises(ValueError, match="URL host not allowed"):
        ingestion._fetch_url_with_safe_redirects("https://example.com/article")


def test_safe_redirect_chain_is_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", _resolver({"example.com": "93.184.216.34", "cdn.example.com": "93.184.216.40"})
    )
    responses = [
        _FakeResp(is_redirect=True, location="https://cdn.example.com/x"),
        _FakeResp(is_redirect=False, text="<html>final</html>"),
    ]
    monkeypatch.setattr(ingestion.httpx, "Client", lambda **kw: _FakeClient(responses))

    final_url, html = ingestion._fetch_url_with_safe_redirects("https://example.com/article")
    assert final_url == "https://cdn.example.com/x"
    assert "final" in html


def test_too_many_redirects_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({}))  # everything public
    # More redirects than the cap.
    responses = [_FakeResp(is_redirect=True, location="https://example.com/next") for _ in range(10)]
    monkeypatch.setattr(ingestion.httpx, "Client", lambda **kw: _FakeClient(responses))

    with pytest.raises(ValueError, match="Too many redirects"):
        ingestion._fetch_url_with_safe_redirects("https://example.com/start")
