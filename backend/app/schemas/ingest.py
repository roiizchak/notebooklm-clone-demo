"""Pydantic model for per-source-type ingest payloads."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class IngestPayload(BaseModel):
    """Discriminated payload passed from the source router into the ingest task.

    Replaces the previous bare-dict hand-off. The downstream `run_ingest`
    branches in `app.services.ingestion` unpack the dict by key
    (`content` for text, `url` for url/youtube, `storage_path` for upload).
    The `body` field is aliased to `content` on serialization so
    `.model_dump(mode="json")` produces the dict shape ingestion expects.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source_type: Literal["text", "url", "youtube", "upload"]
    name: str

    # text — accepts `body` in Python, serializes as `content` to match
    # the key `ingestion.run_ingest` reads.
    body: str | None = Field(default=None, serialization_alias="content")

    # url, youtube
    url: HttpUrl | None = None

    # upload
    storage_path: str | None = None
    original_filename: str | None = None
    content_type: str | None = None
    file_size_bytes: int | None = None

    @model_validator(mode="after")
    def _check_per_type_fields(self) -> "IngestPayload":
        st = self.source_type
        if st == "text" and not self.body:
            raise ValueError("text source requires non-empty body")
        if st in ("url", "youtube") and self.url is None:
            raise ValueError(f"{st} source requires url")
        if st == "upload" and not self.storage_path:
            raise ValueError("upload source requires storage_path")
        return self
