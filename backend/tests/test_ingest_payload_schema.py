"""B-COR-08: IngestPayload validates source_type + per-type fields."""

import pytest
from pydantic import ValidationError


def test_text_payload_requires_body() -> None:
    from app.schemas.ingest import IngestPayload

    with pytest.raises(ValidationError):
        IngestPayload(source_type="text", name="t")  # body missing

    p = IngestPayload(source_type="text", name="t", body="hello")
    assert p.body == "hello"


def test_url_payload_requires_url() -> None:
    from app.schemas.ingest import IngestPayload

    with pytest.raises(ValidationError):
        IngestPayload(source_type="url", name="u")

    p = IngestPayload(source_type="url", name="u", url="https://example.com")
    assert str(p.url).startswith("https://example.com")


def test_upload_payload_requires_storage_path() -> None:
    from app.schemas.ingest import IngestPayload

    with pytest.raises(ValidationError):
        IngestPayload(source_type="upload", name="f")

    p = IngestPayload(
        source_type="upload",
        name="f",
        storage_path="user/notebook/src/file.pdf",
        original_filename="file.pdf",
        content_type="application/pdf",
    )
    assert p.storage_path.endswith("file.pdf")


def test_youtube_payload_requires_url() -> None:
    from app.schemas.ingest import IngestPayload

    with pytest.raises(ValidationError):
        IngestPayload(source_type="youtube", name="y")

    p = IngestPayload(
        source_type="youtube",
        name="y",
        url="https://youtu.be/dQw4w9WgXcQ",
    )
    assert "youtu.be" in str(p.url)
