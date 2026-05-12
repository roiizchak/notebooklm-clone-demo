"""Audio overview generation pipeline.

Multi-speaker dialogue (Alice + Bob) generated from notebook sources via:
  1. Pull source chunks (representative sample across all ready sources).
  2. Generate transcript with Gemini chat model.
  3. Synthesize WAV via gemini-3.1-flash-tts-preview multi-speaker config.
  4. Upload WAV bytes to the `audio` Supabase Storage bucket.
  5. Mark the `audio_overviews` row `ready` (or `failed` on any exception).

Runs detached as a FastAPI BackgroundTask. Vercel serverless function ceiling
is 300s; 5- and 10-minute audio fits comfortably, 15-minute target may
exceed and is captured as a `failed` status with retryable error.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.services.gemini import (
    SpeakerVoice,
    TRANSCRIPT_MODEL,
    TTS_MODEL,
    get_gemini,
)
from app.services.storage import upload_bytes
from app.services.supabase_client import get_supabase
from app.services.usage import log_usage

log = logging.getLogger(__name__)

AUDIO_BUCKET = "audio"

# Hardcoded speaker pair (Phase 2). Phase 3 may make these user-configurable.
DEFAULT_SPEAKERS: tuple[SpeakerVoice, ...] = (
    SpeakerVoice(speaker="Alice", voice_name="Kore"),
    SpeakerVoice(speaker="Bob", voice_name="Puck"),
)

# Maximum characters of source content fed into the transcript prompt.
# Roughly 50k chars ~= 12-15k tokens, fits comfortably in flash-preview's window.
MAX_CONTEXT_CHARS = 50_000

# Per-source chunk cap: take up to this many of each source's earliest chunks
# so very large sources do not crowd out smaller ones.
PER_SOURCE_CHUNK_CAP = 30


@dataclass
class _AudioContext:
    text: str
    source_ids: list[str]


def enqueue_audio_generation(
    *,
    notebook_id: str,
    user_id: str,
    target_minutes: int,
    custom_instructions: str | None,
) -> dict:
    """Insert the `audio_overviews` row (status='pending') and return it.

    Caller is responsible for adding `_run_audio_generation` to BackgroundTasks.
    """
    sb = get_supabase()
    res = (
        sb.table("audio_overviews")
        .insert(
            {
                "notebook_id": notebook_id,
                "user_id": user_id,
                "status": "pending",
                "target_minutes": target_minutes,
                "custom_instructions": custom_instructions,
                "model_script": TRANSCRIPT_MODEL,
                "model_tts": TTS_MODEL,
            }
        )
        .execute()
    )
    if not res.data:
        raise RuntimeError("Failed to create audio_overviews row")
    return res.data[0]


def _mark(audio_id: str, fields: dict) -> None:
    """Update audio_overviews row. Retries once on transient error (B-COR-04)."""
    import time

    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            get_supabase().table("audio_overviews").update(fields).eq(
                "id", audio_id
            ).execute()
            if attempt == 2:
                log.warning("audio._mark succeeded on retry audio_id=%s", audio_id)
            return
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt == 1:
                time.sleep(0.5)
                continue
    log.error(
        "STUCK_ROW audio._mark exhausted retries audio_id=%s err=%s",
        audio_id,
        str(last_exc)[:200],
    )


def _gather_context(notebook_id: str) -> _AudioContext:
    """Pull a representative sample of source chunks for the notebook.

    Strategy: load up to PER_SOURCE_CHUNK_CAP earliest chunks per ready
    source, concatenate with light separators, then truncate to
    MAX_CONTEXT_CHARS. Earliest-chunks-first preserves narrative flow for
    documents that have one (intro / abstract / opening sections).
    """
    sb = get_supabase()
    sources_res = (
        sb.table("sources")
        .select("id,name")
        .eq("notebook_id", notebook_id)
        .eq("status", "ready")
        .execute()
    )
    sources = sources_res.data or []
    if not sources:
        return _AudioContext(text="", source_ids=[])

    source_ids = [s["id"] for s in sources]

    # P-PRF-01: single batched query instead of N+1.
    chunk_res = (
        sb.table("source_chunks")
        .select("source_id,content,chunk_index")
        .in_("source_id", source_ids)
        .order("chunk_index", desc=False)
        .execute()
    )
    by_src: dict[str, list[dict]] = {}
    for row in (chunk_res.data or []):
        sid = row.get("source_id")
        if sid is None:
            continue
        by_src.setdefault(sid, []).append(row)

    pieces: list[str] = []
    used_source_ids: list[str] = []
    for s in sources:
        rows = by_src.get(s["id"], [])[:PER_SOURCE_CHUNK_CAP]
        if not rows:
            continue
        text = "\n".join(r["content"] for r in rows)
        pieces.append(f"=== Source: {s['name']} ===\n{text}")
        used_source_ids.append(s["id"])

    full = "\n\n".join(pieces)
    if len(full) > MAX_CONTEXT_CHARS:
        full = full[:MAX_CONTEXT_CHARS]
    return _AudioContext(text=full, source_ids=used_source_ids)


def _audio_storage_path(user_id: str, notebook_id: str, audio_id: str) -> str:
    return f"{user_id}/{notebook_id}/{audio_id}.wav"


async def _generate_audio_async(audio_id: str) -> None:
    sb = get_supabase()
    row_res = (
        sb.table("audio_overviews")
        .select("*")
        .eq("id", audio_id)
        .limit(1)
        .execute()
    )
    if not row_res.data:
        log.error("audio row %s not found", audio_id)
        return
    row = row_res.data[0]
    user_id = row["user_id"]
    notebook_id = row["notebook_id"]
    target_minutes = int(row["target_minutes"])
    custom_instructions = row.get("custom_instructions")

    _mark(audio_id, {"status": "generating"})

    try:
        ctx = await asyncio.to_thread(_gather_context, notebook_id)
        if not ctx.text.strip():
            raise RuntimeError("Notebook has no ready sources")

        gemini = get_gemini()

        # 1. Transcript.
        transcript = await asyncio.to_thread(
            lambda: gemini.generate_transcript(
                context=ctx.text,
                target_minutes=target_minutes,
                custom_instructions=custom_instructions,
                speakers=DEFAULT_SPEAKERS,
            )
        )
        script = transcript.content.strip()
        if not script:
            raise RuntimeError("Transcript generation returned empty content")

        # 2. TTS.
        tts = await asyncio.to_thread(
            lambda: gemini.synthesize_dialogue(
                script=script,
                speakers=DEFAULT_SPEAKERS,
            )
        )

        # 3. Upload WAV.
        path = _audio_storage_path(user_id, notebook_id, audio_id)
        await asyncio.to_thread(
            upload_bytes,
            AUDIO_BUCKET,
            path,
            tts.wav_bytes,
            "audio/wav",
        )

        total_cost = (transcript.usage.cost_usd or 0.0) + (tts.usage.cost_usd or 0.0)
        _mark(
            audio_id,
            {
                "status": "ready",
                "script": script,
                "audio_path": path,
                "duration_seconds": int(tts.duration_seconds),
                "source_ids": ctx.source_ids,
                "cost_usd": total_cost,
            },
        )

        # Best-effort usage logging (separate rows for each model).
        log_usage(
            user_id=user_id,
            notebook_id=notebook_id,
            operation_type="audio_transcript",
            usage=transcript.usage,
            metadata={"audio_id": audio_id},
        )
        log_usage(
            user_id=user_id,
            notebook_id=notebook_id,
            operation_type="audio_tts",
            usage=tts.usage,
            metadata={
                "audio_id": audio_id,
                "duration_seconds": int(tts.duration_seconds),
            },
        )
    except Exception as e:  # noqa: BLE001
        log.exception("audio generation failed for %s", audio_id)
        _mark(audio_id, {"status": "failed", "error": str(e)[:500]})


def run_audio_generation_blocking(audio_id: str) -> None:
    """Sync wrapper for FastAPI BackgroundTasks (matches ingestion pattern)."""
    asyncio.run(_generate_audio_async(audio_id))
