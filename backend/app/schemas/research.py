"""Pydantic models for the deep research pipeline.

These are internal dataclass-like models used by ``app.services.research``.
The API I/O models (ResearchReportOut, ResearchCreateAck, etc.) live in
``app.models.schemas`` alongside the other public-facing schemas.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SectionStatus = Literal["pending", "researching", "ready", "failed"]
ResearchStatus = Literal["pending", "researching", "ready", "failed", "partial"]


class PlanSection(BaseModel):
    """One outline section the planner produced."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(..., min_length=1, max_length=200)
    sub_query: str = Field(..., min_length=1, max_length=500)
    rationale: str = Field(default="", max_length=500)


class Plan(BaseModel):
    """The plan LLM output, parsed into structured form."""

    model_config = ConfigDict(extra="ignore")

    tldr_hint: str = Field(default="", max_length=2000)
    sections: list[PlanSection] = Field(..., min_length=1, max_length=5)
    expected_gaps: list[str] = Field(default_factory=list)


class SectionCitation(BaseModel):
    """One citation inside a section, numbered locally (1..k per section).

    Mirrors ``rag.Citation``/``schemas.CitationOut`` but with ``number``
    being section-local. The stitch step renumbers globally and writes
    a flat list onto ``research_reports.citations``.
    """

    model_config = ConfigDict(extra="ignore")

    number: int
    chunk_id: str
    source_id: str
    source_name: str
    text_excerpt: str
    metadata: dict
    similarity: float


class SectionDraft(BaseModel):
    """A finished section ready to be persisted into ``sections`` JSONB."""

    model_config = ConfigDict(extra="ignore")

    title: str
    sub_query: str
    content_md: str
    citations: list[SectionCitation] = Field(default_factory=list)
    status: SectionStatus = "ready"
    error: str | None = None
