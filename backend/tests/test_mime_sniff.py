"""F6a: magic-byte sniffing rejects content that doesn't match the declared type."""

from __future__ import annotations

from app.routers.sources import _content_matches_declared_type


def test_pdf_magic_accepts_real_pdf() -> None:
    assert _content_matches_declared_type("pdf", b"%PDF-1.7\n...") is True


def test_pdf_magic_rejects_html_disguised_as_pdf() -> None:
    assert _content_matches_declared_type("pdf", b"<html><body>nope") is False


def test_docx_magic_accepts_zip_container() -> None:
    assert _content_matches_declared_type("docx", b"PK\x03\x04rest") is True


def test_docx_magic_rejects_non_zip() -> None:
    assert _content_matches_declared_type("docx", b"%PDF-1.7") is False


def test_text_is_not_sniffed() -> None:
    # Text is validated via utf-8 decode elsewhere; sniff is a no-op pass.
    assert _content_matches_declared_type("text", b"\x00\x01\x02") is True
