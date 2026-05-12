"""Source ingestion pipeline.

Per-type extractors (PDF, DOCX, URL, YouTube, text) emit ordered text blocks
with metadata (page / paragraph / timestamp). Blocks are merged then split
into sentence-aware chunks (~800 tokens, 100 overlap), embedded in batches,
and stored in `source_chunks`.

A single source has a 200k-token hard cap to keep ingest time within Vercel's
300s function ceiling. Body size is independently capped at 4MB by the router.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import httpx

from app.services.gemini import EMBED_DIM, get_gemini, Usage
from app.services.supabase_client import get_supabase

log = logging.getLogger(__name__)

# Limits
MAX_TOKENS_PER_SOURCE = 200_000
CHUNK_TARGET_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 100
EMBED_BATCH_SIZE = 100

# 1 token ~= 4 chars (rough)
CHARS_PER_TOKEN = 4

# Allowed YouTube URL host suffixes.
_YOUTUBE_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")
_YOUTUBE_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/))([A-Za-z0-9_-]{11})"
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'\(])")


# ---------- Data classes ----------


@dataclass
class TextBlock:
    """A unit of source text with positional metadata."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    chunk_index: int
    content: str
    token_count: int
    metadata: dict[str, Any]


@dataclass
class IngestResult:
    chunks_created: int
    total_tokens: int
    summary_payload: dict | None
    embed_usage: Usage
    summary_usage: Usage | None


# ---------- Extractors ----------


def extract_text(content: str, *, name: str | None = None) -> list[TextBlock]:
    """Pasted text source."""
    text = content.strip()
    if not text:
        return []
    return [TextBlock(content=text, metadata={"source_kind": "text"})]


def extract_pdf(file_bytes: bytes) -> list[TextBlock]:
    from pypdf import PdfReader
    from io import BytesIO

    reader = PdfReader(BytesIO(file_bytes))
    blocks: list[TextBlock] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as e:  # noqa: BLE001 — pypdf raises many internal classes (PdfReadError, ParseError, IndexError) on malformed pages; skip-and-continue is intentional
            log.warning("pdf page %d extract failed: %s", i, e)
            continue
        text = text.strip()
        if text:
            blocks.append(TextBlock(content=text, metadata={"page": i}))
    return blocks


def extract_docx(file_bytes: bytes) -> list[TextBlock]:
    from docx import Document
    from io import BytesIO

    doc = Document(BytesIO(file_bytes))
    blocks: list[TextBlock] = []
    para_index = 0
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        para_index += 1
        blocks.append(TextBlock(content=text, metadata={"paragraph": para_index}))
    return blocks


def _is_safe_url_target(url: str) -> bool:
    """SSRF guard: reject loopback, link-local, and private IPs."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    if host in ("localhost",) or host.endswith(".localhost"):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return False
    return True


def extract_url(url: str) -> list[TextBlock]:
    if not _is_safe_url_target(url):
        raise ValueError("URL host not allowed")

    import trafilatura

    # http2=False: the sync httpx HTTP/2 multiplexer can hit WinError 10035
    # under concurrent loads on Windows. HTTP/1.1 is sufficient here.
    with httpx.Client(
        timeout=15.0,
        follow_redirects=True,
        max_redirects=3,
        http2=False,
    ) as client:
        resp = client.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; NotebookLM-Reimagined/0.1; +https://example.com)"
                )
            },
        )
        resp.raise_for_status()
        html = resp.text

    extracted = trafilatura.extract(html, url=url, favor_recall=True) or ""
    text = extracted.strip()
    if not text:
        raise ValueError("URL contained no extractable text")
    return [
        TextBlock(
            content=text,
            metadata={
                "url": url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    ]


def _parse_youtube_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname not in _YOUTUBE_HOSTS:
        raise ValueError("Not a YouTube URL")
    m = _YOUTUBE_ID_RE.search(url)
    if not m:
        raise ValueError("Could not parse YouTube video id")
    return m.group(1)


def extract_youtube(url: str) -> list[TextBlock]:
    # youtube-transcript-api >=1.0 uses an instance API (`fetch`), not the
    # legacy static `get_transcript`.
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    video_id = _parse_youtube_id(url)
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id)
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
        raise ValueError(f"No transcript available: {e}") from e

    snippets = list(fetched.snippets)
    if not snippets:
        raise ValueError("Transcript was empty")

    blocks: list[TextBlock] = []
    WINDOW_SECONDS = 30.0
    window: list = []
    window_start: float | None = None

    def flush_window(end_time: float) -> None:
        if not window or window_start is None:
            return
        text = " ".join(s.text.strip() for s in window if s.text.strip())
        if text:
            blocks.append(
                TextBlock(
                    content=text,
                    metadata={
                        "video_id": video_id,
                        "start": round(window_start, 2),
                        "end": round(end_time, 2),
                    },
                )
            )

    for snip in snippets:
        if window_start is None:
            window_start = float(snip.start)
        window.append(snip)
        end = float(snip.start) + float(snip.duration or 0)
        if end - window_start >= WINDOW_SECONDS:
            flush_window(end)
            window = []
            window_start = None

    if window:
        last = window[-1]
        end = float(last.start) + float(last.duration or 0)
        flush_window(end)

    if not blocks:
        raise ValueError("Transcript was empty")
    return blocks


# ---------- Chunking ----------


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def chunk_blocks(blocks: Iterable[TextBlock]) -> list[Chunk]:
    """Sentence-aware chunker.

    Concatenates sentences within a TextBlock until ~800 tokens, then
    starts a new chunk with ~100 tokens of overlap. Per-block metadata
    is preserved on each chunk derived from that block.
    """
    chunks: list[Chunk] = []
    chunk_idx = 0

    for block in blocks:
        sentences = _SENTENCE_SPLIT_RE.split(block.content) if block.content else []
        # Filter empties.
        sentences = [s.strip() for s in sentences if s.strip()]

        current: list[str] = []
        current_tokens = 0
        for sent in sentences:
            sent_tokens = estimate_tokens(sent)
            if current and current_tokens + sent_tokens > CHUNK_TARGET_TOKENS:
                content = " ".join(current).strip()
                chunks.append(
                    Chunk(
                        chunk_index=chunk_idx,
                        content=content,
                        token_count=current_tokens,
                        metadata=dict(block.metadata),
                    )
                )
                chunk_idx += 1
                # Build overlap from tail.
                overlap: list[str] = []
                overlap_tokens = 0
                for s in reversed(current):
                    t = estimate_tokens(s)
                    if overlap_tokens + t > CHUNK_OVERLAP_TOKENS:
                        break
                    overlap.insert(0, s)
                    overlap_tokens += t
                current = overlap
                current_tokens = overlap_tokens
            current.append(sent)
            current_tokens += sent_tokens

        if current:
            content = " ".join(current).strip()
            chunks.append(
                Chunk(
                    chunk_index=chunk_idx,
                    content=content,
                    token_count=current_tokens,
                    metadata=dict(block.metadata),
                )
            )
            chunk_idx += 1

    return chunks


# ---------- Pipeline ----------


def _total_tokens(chunks: list[Chunk]) -> int:
    return sum(c.token_count for c in chunks)


async def run_ingest(
    *,
    source_id: str,
    notebook_id: str,
    source_type: str,
    payload: dict,
    file_bytes: bytes | None = None,
) -> IngestResult:
    """Execute the full ingest pipeline for a single source.

    `payload` carries type-specific input:
      - text:    {"content": "..."}
      - url:     {"url": "..."}
      - youtube: {"url": "..."}
      - pdf/docx: {} (use `file_bytes`)
    """
    extractor: Callable[[], list[TextBlock]]
    if source_type == "text":
        extractor = lambda: extract_text(payload["content"])
    elif source_type == "url":
        extractor = lambda: extract_url(payload["url"])
    elif source_type == "youtube":
        extractor = lambda: extract_youtube(payload["url"])
    elif source_type == "pdf":
        if file_bytes is None:
            raise ValueError("pdf source missing file_bytes")
        extractor = lambda: extract_pdf(file_bytes)
    elif source_type == "docx":
        if file_bytes is None:
            raise ValueError("docx source missing file_bytes")
        extractor = lambda: extract_docx(file_bytes)
    else:
        raise ValueError(f"Unsupported source type: {source_type}")

    # Run extraction off the event loop (sync libs).
    blocks = await asyncio.to_thread(extractor)
    if not blocks:
        raise ValueError("Source contained no extractable text")

    chunks = chunk_blocks(blocks)
    total_tokens = _total_tokens(chunks)
    if total_tokens > MAX_TOKENS_PER_SOURCE:
        raise ValueError(
            f"Source too large: {total_tokens} tokens (max {MAX_TOKENS_PER_SOURCE})"
        )

    # Embed in batches.
    gemini = get_gemini()
    all_vectors: list[list[float]] = []
    embed_usage = Usage(model_used="gemini-embedding-2")
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[i : i + EMBED_BATCH_SIZE]
        texts = [c.content for c in batch]
        result = await asyncio.to_thread(gemini.embed_documents, texts)
        if any(len(v) != EMBED_DIM for v in result.vectors):
            raise RuntimeError(
                f"Unexpected embedding dimension; expected {EMBED_DIM}"
            )
        all_vectors.extend(result.vectors)
        embed_usage.input_tokens += result.usage.input_tokens
        embed_usage.cost_usd += result.usage.cost_usd

    assert len(all_vectors) == len(chunks)

    sb = get_supabase()

    # Insert chunks.
    rows = [
        {
            "source_id": source_id,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "token_count": chunk.token_count,
            "embedding": all_vectors[i],
            "metadata": chunk.metadata,
        }
        for i, chunk in enumerate(chunks)
    ]
    # Insert in batches of 50 to keep request sizes reasonable.
    for i in range(0, len(rows), 50):
        sb.table("source_chunks").insert(rows[i : i + 50]).execute()

    # Build summary from concatenated chunk content (truncated inside the call).
    full_text = "\n\n".join(c.content for c in chunks)
    summary_usage: Usage | None = None
    summary_payload: dict | None = None
    try:
        summary_result = await asyncio.to_thread(gemini.generate_summary, full_text)
        import json

        summary_payload = json.loads(summary_result.content) if summary_result.content else None
        summary_usage = summary_result.usage
    except Exception as e:  # noqa: BLE001
        log.warning("summary generation failed for source %s: %s", source_id, e)

    return IngestResult(
        chunks_created=len(chunks),
        total_tokens=total_tokens,
        summary_payload=summary_payload,
        embed_usage=embed_usage,
        summary_usage=summary_usage,
    )
