"""SSRF guard tests."""

import socket

import pytest

from app.services.ingestion import _is_safe_url_target


def _stub_resolve(monkeypatch, ip: str) -> None:
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def test_rejects_localhost() -> None:
    assert _is_safe_url_target("http://localhost/foo") is False


def test_rejects_loopback_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolve(monkeypatch, "127.0.0.1")
    assert _is_safe_url_target("http://example-attacker.com/") is False


def test_rejects_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolve(monkeypatch, "10.0.0.5")
    assert _is_safe_url_target("http://intranet.attacker/") is False


def test_rejects_link_local(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolve(monkeypatch, "169.254.169.254")
    assert _is_safe_url_target("http://metadata.attacker/") is False


def test_rejects_non_http_scheme() -> None:
    assert _is_safe_url_target("file:///etc/passwd") is False
    assert _is_safe_url_target("gopher://x/") is False


def test_accepts_normal_public_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolve(monkeypatch, "93.184.216.34")  # example.com
    assert _is_safe_url_target("https://example.com/article") is True
