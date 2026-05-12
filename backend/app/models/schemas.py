"""Pydantic request / response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

# ---------- Notebooks ----------


class NotebookCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    emoji: str = Field(default="📓", max_length=8)
    description: str | None = Field(default=None, max_length=2000)


class NotebookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    emoji: str | None = Field(default=None, max_length=8)
    description: str | None = Field(default=None, max_length=2000)


class NotebookOut(BaseModel):
    id: str
    user_id: str
    name: str
    description: str | None
    emoji: str
    settings: dict
    source_count: int
    created_at: datetime
    updated_at: datetime


# ---------- Sources ----------


SourceType = Literal["pdf", "docx", "url", "youtube", "text"]
SourceStatus = Literal["pending", "processing", "ready", "failed"]


class SourceUrlIn(BaseModel):
    url: HttpUrl


class SourceTextIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=400_000)


class SourceOut(BaseModel):
    id: str
    notebook_id: str
    type: SourceType
    name: str
    status: SourceStatus
    file_path: str | None
    original_filename: str | None
    mime_type: str | None
    file_size_bytes: int | None
    token_count: int | None
    metadata: dict
    source_guide: dict | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class SourceCreatedAck(BaseModel):
    """Returned after starting an async ingest job."""

    id: str
    status: SourceStatus = "processing"


# ---------- Chat ----------


ChatMode = Literal["chat", "research"]


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = None
    source_ids: list[str] | None = None
    model: str | None = None
    mode: ChatMode = "chat"


class CitationOut(BaseModel):
    number: int
    chunk_id: str
    source_id: str
    source_name: str
    text_excerpt: str
    metadata: dict
    similarity: float


class UsageOut(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model_used: str


class ChatResponse(BaseModel):
    message_id: str
    session_id: str
    content: str
    citations: list[CitationOut]
    suggested_questions: list[str] = Field(default_factory=list)
    usage: UsageOut


class ChatSessionOut(BaseModel):
    id: str
    notebook_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    citations: list[dict]
    source_ids_used: list[str]
    model_used: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    created_at: datetime
    mode: ChatMode = "chat"
    research_report_id: str | None = None


class ChatSessionDetail(BaseModel):
    session: ChatSessionOut
    messages: list[ChatMessageOut]


# ---------- Phase 2: Study materials ----------


StudyKind = Literal["flashcards", "quiz", "study_guide", "faq"]


class StudyMaterialOut(BaseModel):
    id: str
    notebook_id: str
    user_id: str
    kind: StudyKind
    payload: dict
    source_ids: list[str] = Field(default_factory=list)
    model_used: str
    cost_usd: float | None
    created_at: datetime
    updated_at: datetime


# ---------- Phase 2: Notes ----------


NoteType = Literal["written", "saved_response"]


class NoteCreate(BaseModel):
    type: NoteType
    title: str | None = Field(default=None, max_length=200)
    content: str = Field(..., min_length=1, max_length=200_000)
    tags: list[str] | None = None
    is_pinned: bool | None = False
    original_message_id: str | None = None


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=200_000)
    tags: list[str] | None = None
    is_pinned: bool | None = None


class NoteOut(BaseModel):
    id: str
    notebook_id: str
    user_id: str
    type: NoteType
    title: str | None
    content: str
    tags: list[str]
    is_pinned: bool
    original_message_id: str | None
    created_at: datetime
    updated_at: datetime


# ---------- Phase 2: Audio overviews ----------


AudioStatus = Literal["pending", "generating", "ready", "failed"]
AudioMinutes = Literal[5, 10, 15]


class AudioGenerateIn(BaseModel):
    target_minutes: AudioMinutes = 10
    custom_instructions: str | None = Field(default=None, max_length=2000)


class AudioOverviewOut(BaseModel):
    id: str
    notebook_id: str
    user_id: str
    status: AudioStatus
    target_minutes: int
    custom_instructions: str | None
    source_ids: list[str]
    script: str | None
    audio_path: str | None
    duration_seconds: int | None
    error: str | None
    cost_usd: float | None
    model_script: str | None
    model_tts: str | None
    created_at: datetime
    updated_at: datetime


# ---------- Phase 2: Direct-upload signed URLs ----------


class UploadInitIn(BaseModel):
    filename: str = Field(..., min_length=1, max_length=300)
    mime_type: str = Field(..., min_length=1, max_length=200)
    size: int = Field(..., ge=1, le=52_428_800)  # max 50 MiB


class UploadInitOut(BaseModel):
    source_id: str
    storage_path: str
    signed_url: str
    token: str
    expires_in: int


class UploadCompleteIn(BaseModel):
    source_id: str


# ---------- Profile ----------


class ProfileOut(BaseModel):
    id: str
    email: str | None
    name: str | None
    avatar_url: str | None
    settings: dict
    created_at: datetime
    updated_at: datetime


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    avatar_url: str | None = None
    settings: dict | None = None


# ---------- Phase 3.a: Deep research mode ----------


ResearchStatus = Literal["pending", "researching", "ready", "failed", "partial"]


class ResearchCreateAck(BaseModel):
    """Returned by ``POST /chat`` when ``mode='research'``.

    The request is accepted (HTTP 202) and a BackgroundTask runs the pipeline.
    Frontend polls ``GET /notebooks/{id}/research/{research_report_id}``.
    """

    message_id: str
    session_id: str
    research_report_id: str
    status: ResearchStatus = "pending"


class ResearchReportSectionOut(BaseModel):
    title: str
    sub_query: str | None = None
    content_md: str | None = None
    citations: list[dict] = Field(default_factory=list)
    status: Literal["pending", "researching", "ready", "failed"] = "pending"
    error: str | None = None


class ResearchReportOut(BaseModel):
    id: str
    notebook_id: str
    user_id: str
    session_id: str | None
    question: str
    source_ids: list[str] = Field(default_factory=list)
    status: ResearchStatus
    plan: dict | None
    sections: list[ResearchReportSectionOut] = Field(default_factory=list)
    content_md: str | None
    citations: list[dict] = Field(default_factory=list)
    model_plan: str | None
    model_sections: str | None
    model_stitch: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


# ---------- Wrapper ----------


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ApiErrorResponse(BaseModel):
    error: ApiError
