"""Gemini API client wrapper.

Encapsulates:
- Embedding (`gemini-embedding-2`, 1536 dim, MRL).
- Chat (`gemini-3-flash-preview` default, `gemini-3.1-flash-lite` allowed).
- Multi-speaker TTS (`gemini-3.1-flash-tts-preview`, Phase 2 audio overviews).
- Structured-JSON study materials (Phase 2 flashcards/quiz/study_guide/faq).
- Cost calculation per the May 2026 verified pricing table.

Uses the `google-genai` SDK.
"""

from __future__ import annotations

import io
import json
import wave
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from google import genai
from google.genai import types as genai_types

from app.config import get_settings

# Model identifiers (verified May 2026).
EMBED_MODEL = "gemini-embedding-2"
CHAT_DEFAULT = "gemini-3-flash-preview"
CHAT_ALLOWED: tuple[str, ...] = (
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-3.1-pro-preview",  # Phase 3.a: deep research stitch step.
)
SUMMARY_MODEL = "gemini-3.1-flash-lite"  # Cheap model for source summaries / titles.
STUDY_MODEL = "gemini-3.1-flash-lite"    # Phase 2: study materials JSON gen.
TRANSCRIPT_MODEL = "gemini-3-flash-preview"  # Phase 2: podcast dialogue transcript.
TTS_MODEL = "gemini-3.1-flash-tts-preview"   # Phase 2: multi-speaker TTS.

# Phase 3.a: deep research mode model ladder.
RESEARCH_PLAN_MODEL = "gemini-3-flash-preview"
RESEARCH_SECTION_MODEL = "gemini-3-flash-preview"
RESEARCH_STITCH_MODEL = "gemini-3.1-pro-preview"

EMBED_DIM = 1536

# TTS audio output format (Gemini returns 24kHz mono PCM16; we wrap in WAV).
TTS_SAMPLE_RATE = 24000
TTS_CHANNELS = 1
TTS_SAMPLE_WIDTH = 2  # bytes per sample (16-bit)

# USD per 1M tokens. From https://ai.google.dev/gemini-api/docs/pricing
# TTS audio output is billed at 25 tokens per second of audio.
# Pro pricing is for prompts <=200k tokens; >200k tier ($4.00/$18.00) not used here
# because deep research caps the stitch input well below that threshold.
_PRICING: dict[str, dict[str, float]] = {
    "gemini-embedding-2": {"input": 0.20, "output": 0.0},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
    "gemini-3.1-flash-tts-preview": {"input": 1.00, "output": 20.00},
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = _PRICING.get(model)
    if not p:
        return 0.0
    return (input_tokens / 1_000_000) * p["input"] + (output_tokens / 1_000_000) * p["output"]


def is_chat_model_allowed(model: str) -> bool:
    return model in CHAT_ALLOWED


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    model_used: str = ""
    cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model_used": self.model_used,
            "cost_usd": self.cost_usd,
        }


@dataclass
class EmbedResult:
    vectors: list[list[float]]
    usage: Usage


@dataclass
class ChatResult:
    content: str
    usage: Usage


@dataclass
class GroundingHit:
    """One web source returned by Gemini google_search grounding.

    Its index in the parent list is the local citation number (1-based at
    render time). Used by Phase 3.a knowledge-only research sections to
    produce real web citations.
    """
    uri: str
    title: str = ""


@dataclass
class GroundingSupport:
    """A pointer from a text span in the section back to one or more hits.

    `end_index` is a UTF-8 byte offset into the section text per the Gemini
    grounding spec. Callers should splice citation tokens by manipulating
    bytes (not characters) to keep multi-byte sequences intact.
    """
    end_index: int
    text_segment: str
    hit_indices: list[int]   # 0-based indices into the hits list
    confidence: float = 1.0


def _extract_grounding(response: object) -> tuple[list[GroundingHit], list[GroundingSupport]]:
    """Parse `grounding_metadata.grounding_chunks` + `.grounding_supports` from a Gemini response.

    Returns ``(hits, supports)`` -- both empty when grounding is absent so
    callers degrade gracefully (knowledge-only output keeps working with no
    citations rather than throwing).

    On unexpected shapes (preview-SDK churn) the helper also logs a
    once-per-call diagnostic at INFO so operators can spot grounding
    silently going missing without instrumenting Gemini end-to-end.
    """
    import logging as _logging

    _log = _logging.getLogger(__name__)

    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        _log.info("gemini grounding: response had no candidates")
        return [], []
    grounding = getattr(candidates[0], "grounding_metadata", None)
    if grounding is None:
        _log.info(
            "gemini grounding: candidates[0] has no grounding_metadata "
            "(attrs=%s)",
            sorted([a for a in dir(candidates[0]) if not a.startswith("_")])[:15],
        )
        return [], []
    raw_chunks = getattr(grounding, "grounding_chunks", None) or []
    raw_supports = getattr(grounding, "grounding_supports", None) or []
    if not raw_chunks and not raw_supports:
        _log.info(
            "gemini grounding: grounding_metadata present but empty "
            "(attrs=%s)",
            sorted([a for a in dir(grounding) if not a.startswith("_")])[:15],
        )

    hits: list[GroundingHit] = []
    for chunk in raw_chunks:
        web = getattr(chunk, "web", None)
        if web is None:
            hits.append(GroundingHit(uri="", title=""))
            continue
        uri = getattr(web, "uri", "") or ""
        title = getattr(web, "title", "") or ""
        hits.append(GroundingHit(uri=uri, title=title))

    supports: list[GroundingSupport] = []
    for sup in raw_supports:
        segment = getattr(sup, "segment", None)
        if segment is None:
            continue
        end_index = int(getattr(segment, "end_index", 0) or 0)
        text_segment = getattr(segment, "text", "") or ""
        chunk_indices = list(getattr(sup, "grounding_chunk_indices", None) or [])
        scores = list(getattr(sup, "confidence_scores", None) or [])
        confidence = max(scores) if scores else 1.0
        supports.append(GroundingSupport(
            end_index=end_index,
            text_segment=text_segment,
            hit_indices=[int(i) for i in chunk_indices],
            confidence=float(confidence),
        ))
    return hits, supports


@dataclass
class TtsResult:
    """Multi-speaker TTS output."""
    wav_bytes: bytes
    duration_seconds: float
    usage: Usage


@dataclass
class SpeakerVoice:
    speaker: str       # name as referenced in script (e.g. "Alice")
    voice_name: str    # prebuilt Gemini voice id (e.g. "Kore", "Puck")


@dataclass
class GeminiService:
    _client: genai.Client = field(init=False)

    def __post_init__(self) -> None:
        self._client = genai.Client(api_key=get_settings().google_api_key)

    # ----- Embeddings -----

    def embed_documents(self, texts: Sequence[str]) -> EmbedResult:
        return self._embed(texts, task_type="RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> EmbedResult:
        return self._embed([text], task_type="RETRIEVAL_QUERY")

    def _embed(self, texts: Sequence[str], *, task_type: str) -> EmbedResult:
        if not texts:
            return EmbedResult(vectors=[], usage=Usage(model_used=EMBED_MODEL))

        # google-genai's `embed_content` does not reliably return one embedding
        # per content when passed a list (it sometimes returns a single
        # embedding for the concatenated batch, and the count varies across
        # SDK versions). Call once per text to guarantee 1:1 alignment.
        vectors: list[list[float]] = []
        total_tokens = 0
        config = genai_types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=EMBED_DIM,
        )
        for text in texts:
            response = self._client.models.embed_content(
                model=EMBED_MODEL,
                contents=text,
                config=config,
            )
            embeddings = list(response.embeddings or [])
            if not embeddings:
                raise RuntimeError("embed_content returned no embeddings")
            # Pick the first embedding deterministically.
            vectors.append(list(embeddings[0].values))

            tok = getattr(response, "total_billable_tokens", None)
            if tok is None:
                tok = max(1, len(text) // 4)
            total_tokens += int(tok)

        usage = Usage(
            input_tokens=total_tokens,
            output_tokens=0,
            model_used=EMBED_MODEL,
            cost_usd=calculate_cost(EMBED_MODEL, total_tokens, 0),
        )
        return EmbedResult(vectors=vectors, usage=usage)

    # ----- Chat -----

    def generate_chat(
        self,
        *,
        system_instruction: str,
        history: Iterable[dict],
        user_message: str,
        model: str = CHAT_DEFAULT,
        temperature: float = 0.4,
    ) -> ChatResult:
        if not is_chat_model_allowed(model):
            model = CHAT_DEFAULT

        contents: list[genai_types.Content] = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(
                genai_types.Content(
                    role=role,
                    parts=[genai_types.Part(text=msg["content"])],
                )
            )
        contents.append(
            genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=user_message)],
            )
        )

        response = self._client.models.generate_content(
            model=model,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=temperature,
            ),
        )

        meta = response.usage_metadata
        in_tok = int(getattr(meta, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(meta, "candidates_token_count", 0) or 0)

        return ChatResult(
            content=response.text or "",
            usage=Usage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                model_used=model,
                cost_usd=calculate_cost(model, in_tok, out_tok),
            ),
        )

    # ----- Phase 2: transcript / study payload / multi-speaker TTS -----

    def generate_transcript(
        self,
        *,
        context: str,
        target_minutes: int,
        custom_instructions: str | None,
        speakers: Sequence[SpeakerVoice],
    ) -> ChatResult:
        """Generate a podcast-style two-host dialogue transcript.

        Output format MUST be lines of "Speaker: line" so that downstream
        synthesize_dialogue can map speakers to voices.
        """
        # ~150 words per spoken minute is a reasonable English target.
        target_words = max(200, target_minutes * 150)

        speaker_names = [s.speaker for s in speakers]
        if len(speaker_names) < 2:
            raise ValueError("transcript requires at least 2 speakers")

        focus = (
            f"Custom focus: {custom_instructions.strip()}"
            if custom_instructions and custom_instructions.strip()
            else "Cover the most important and useful concepts."
        )

        prompt = (
            f"Generate a {target_minutes}-minute podcast dialogue between "
            f"{speaker_names[0]} and {speaker_names[1]} discussing the source "
            f"material below.\n\n"
            f"Target length: ~{target_words} words.\n"
            f"{focus}\n\n"
            f"Format strictly as alternating lines:\n"
            f"{speaker_names[0]}: <line>\n"
            f"{speaker_names[1]}: <line>\n"
            "Do not include any other text, headings, or stage directions. "
            "Use natural conversational flow. Reference specifics from the "
            "sources without inventing facts.\n\n"
            "--- SOURCES ---\n"
            f"{context}\n"
            "--- END SOURCES ---"
        )

        response = self._client.models.generate_content(
            model=TRANSCRIPT_MODEL,
            contents=[
                genai_types.Content(role="user", parts=[genai_types.Part(text=prompt)]),
            ],
            config=genai_types.GenerateContentConfig(
                temperature=0.7,
            ),
        )
        meta = response.usage_metadata
        in_tok = int(getattr(meta, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(meta, "candidates_token_count", 0) or 0)
        return ChatResult(
            content=response.text or "",
            usage=Usage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                model_used=TRANSCRIPT_MODEL,
                cost_usd=calculate_cost(TRANSCRIPT_MODEL, in_tok, out_tok),
            ),
        )

    def synthesize_dialogue(
        self,
        *,
        script: str,
        speakers: Sequence[SpeakerVoice],
    ) -> TtsResult:
        """Multi-speaker TTS via gemini-3.1-flash-tts-preview.

        The TTS model only switches voices when the prompt is explicitly
        framed as a conversation (matching the format in Google's docs).
        We prepend "TTS the following conversation between <A> and <B>:" so
        the model treats the labelled lines as turns rather than narration.

        Returns WAV-wrapped 24kHz/mono/PCM16 bytes plus duration.
        """
        if len(speakers) < 1:
            raise ValueError("at least one speaker required")

        speaker_voice_configs = [
            genai_types.SpeakerVoiceConfig(
                speaker=s.speaker,
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                        voice_name=s.voice_name,
                    ),
                ),
            )
            for s in speakers
        ]

        if len(speakers) >= 2:
            names = " and ".join(s.speaker for s in speakers)
            framed_script = (
                f"TTS the following conversation between {names}:\n{script.strip()}"
            )
        else:
            framed_script = script.strip()

        response = self._client.models.generate_content(
            model=TTS_MODEL,
            contents=framed_script,
            config=genai_types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=genai_types.SpeechConfig(
                    multi_speaker_voice_config=genai_types.MultiSpeakerVoiceConfig(
                        speaker_voice_configs=speaker_voice_configs,
                    ),
                ),
            ),
        )

        # Extract raw PCM16 bytes from the inline_data part.
        pcm: bytes | None = None
        try:
            parts = response.candidates[0].content.parts
            for part in parts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    pcm = inline.data
                    break
        except (AttributeError, IndexError, TypeError) as exc:  # pragma: no cover - defensive
            raise RuntimeError(f"TTS response missing audio: {exc}") from exc
        if not pcm:
            raise RuntimeError("TTS returned no audio data")

        wav_bytes = _pcm_to_wav(pcm)
        duration = len(pcm) / (TTS_SAMPLE_RATE * TTS_CHANNELS * TTS_SAMPLE_WIDTH)

        meta = getattr(response, "usage_metadata", None)
        in_tok = int(getattr(meta, "prompt_token_count", 0) or 0) if meta else 0
        # Audio output billed at 25 tokens/sec.
        out_tok = int(round(duration * 25))

        return TtsResult(
            wav_bytes=wav_bytes,
            duration_seconds=duration,
            usage=Usage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                model_used=TTS_MODEL,
                cost_usd=calculate_cost(TTS_MODEL, in_tok, out_tok),
            ),
        )

    def generate_study_payload(
        self,
        *,
        kind: str,
        context: str,
    ) -> tuple[dict, ChatResult]:
        """Generate flashcards / quiz / study_guide / faq as structured JSON.

        Returns (parsed_payload_dict, chat_result_for_cost_logging).
        Caller is responsible for shape validation against expected schema.
        """
        prompt = _study_prompt(kind, context)
        response = self._client.models.generate_content(
            model=STUDY_MODEL,
            contents=[
                genai_types.Content(role="user", parts=[genai_types.Part(text=prompt)]),
            ],
            config=genai_types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )
        text = response.text or ""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"study_payload returned invalid JSON: {exc}") from exc

        meta = response.usage_metadata
        in_tok = int(getattr(meta, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(meta, "candidates_token_count", 0) or 0)
        cr = ChatResult(
            content=text,
            usage=Usage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                model_used=STUDY_MODEL,
                cost_usd=calculate_cost(STUDY_MODEL, in_tok, out_tok),
            ),
        )
        return payload, cr

    # ----- Phase 3.a: deep research helpers -----

    def generate_research_plan(
        self,
        *,
        question: str,
        source_summaries: Sequence[dict],
    ) -> tuple[dict, ChatResult]:
        """Generate an outline plan (3-5 sections) for a deep research report.

        Returns (parsed_plan_dict, chat_result). The plan dict has shape:
          {"tldr_hint": str, "sections": [{"title", "sub_query", "rationale"}], "expected_gaps": [str]}
        Caller validates against Plan Pydantic model.

        source_summaries is a list of {"name": str, "summary": str} dicts. If
        empty, the planner runs in knowledge-only mode: sub_query is still a
        focused query but per-section retrieval will hit an empty corpus and
        the section step falls through to knowledge-only drafting.
        """
        has_sources = bool(source_summaries)
        if has_sources:
            # Cap to first 20 sources at 200 chars each so we stay well under
            # plan-step input budget.
            listing = "\n".join(
                f"- {s.get('name', '')}: {(s.get('summary') or '')[:200]}"
                for s in source_summaries[:20]
            )
            system = (
                "You are a research planner. Given a question and a list of available "
                "source documents (names + 1-line summaries), produce an outline for a "
                "3-5 section research report. Return ONLY JSON matching this schema: "
                '{"tldr_hint": str, "sections": [{"title": str, "sub_query": str, '
                '"rationale": str}], "expected_gaps": [str]}. Each sub_query must be a '
                "focused embedding-style retrieval query, not the original question "
                "rephrased. Aim for 3-5 sections."
            )
            prompt = f"Question: {question}\n\nSources:\n{listing}"
        else:
            system = (
                "You are a research planner. No source documents are attached to "
                "this notebook, so the report will be written from your general "
                "knowledge (no citations). Produce an outline for a 3-5 section "
                "research report. Return ONLY JSON matching this schema: "
                '{"tldr_hint": str, "sections": [{"title": str, "sub_query": str, '
                '"rationale": str}], "expected_gaps": [str]}. sub_query should be a '
                "focused angle for drafting that section. Aim for 3-5 sections."
            )
            prompt = f"Question: {question}\n\nSources: (none — knowledge-only mode)"
        response = self._client.models.generate_content(
            model=RESEARCH_PLAN_MODEL,
            contents=[
                genai_types.Content(role="user", parts=[genai_types.Part(text=prompt)]),
            ],
            config=genai_types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.4,
                response_mime_type="application/json",
            ),
        )
        text = response.text or ""
        try:
            plan = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"research_plan returned invalid JSON: {exc}") from exc

        meta = response.usage_metadata
        in_tok = int(getattr(meta, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(meta, "candidates_token_count", 0) or 0)
        cr = ChatResult(
            content=text,
            usage=Usage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                model_used=RESEARCH_PLAN_MODEL,
                cost_usd=calculate_cost(RESEARCH_PLAN_MODEL, in_tok, out_tok),
            ),
        )
        return plan, cr

    def generate_research_section_knowledge(
        self,
        *,
        question: str,
        title: str,
        sub_query: str,
    ) -> tuple[ChatResult, list[GroundingHit], list[GroundingSupport]]:
        """Draft one section of a deep research report using Google Search grounding.

        Used when the notebook has no ready source corpus (knowledge-only mode).
        Returns the raw model text plus the web-source grounding metadata so the
        caller (research.py) can splice ``[n]`` citation tokens at the correct
        byte offsets and build :class:`SectionCitation` entries.

        When grounding is unavailable (SDK older than google_search, quota
        denied, etc.) ``hits`` and ``supports`` come back empty -- the section
        still has content, just no citations.
        """
        system = (
            "You write sections of multi-section research reports. You may use "
            "Google Search results that are automatically retrieved for you to "
            "ground claims in real web sources. Target 300-700 words. Do NOT "
            "apologize, disclaim, or say \"I do not have access to sources\" -- "
            "write the section directly as a confident, informative answer. "
            "Do not include the section title in your output."
        )
        # User prompt carries the full task context. Passing only sub_query
        # produced empty responses in practice (Gemini treated it as an
        # ambiguous fragment), which cascaded into 'all sections failed'.
        user_prompt = (
            f"Research question: {question}\n"
            f"Section title: {title}\n"
            f"Angle for this section: {sub_query}\n\n"
            f"Write the section now, drawing on Google Search results for "
            f"real-world facts and citations."
        )
        response = self._client.models.generate_content(
            model=RESEARCH_SECTION_MODEL,
            contents=[
                genai_types.Content(role="user", parts=[genai_types.Part(text=user_prompt)]),
            ],
            config=genai_types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.4,
                tools=[
                    genai_types.Tool(google_search=genai_types.GoogleSearch()),
                ],
            ),
        )
        meta = response.usage_metadata
        in_tok = int(getattr(meta, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(meta, "candidates_token_count", 0) or 0)
        cr = ChatResult(
            content=response.text or "",
            usage=Usage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                model_used=RESEARCH_SECTION_MODEL,
                cost_usd=calculate_cost(RESEARCH_SECTION_MODEL, in_tok, out_tok),
            ),
        )
        hits, supports = _extract_grounding(response)
        return cr, hits, supports

    def generate_research_section(
        self,
        *,
        question: str,
        title: str,
        chunks: Sequence[dict],
    ) -> ChatResult:
        """Draft one section of a deep research report.

        chunks is the retrieve() output for the section's sub_query. Each chunk
        is rendered as "[N] {source_name}: {content}" so the model can cite
        them with [n] tokens that the caller parses via parse_citations.
        """
        chunk_block = "\n\n".join(
            f"[{i+1}] {c.get('source_name', '')}: {c.get('content', '')[:1200]}"
            for i, c in enumerate(chunks)
        )
        system = (
            f'Write a concise section titled "{title}" for a research report on '
            f'"{question}". Use ONLY the provided chunks below. Cite each '
            "non-trivial claim with [1], [2], etc. matching the chunk numbers "
            "shown. Target 300-700 words. Do not invent citation numbers beyond "
            "the chunks provided. Do not include the section title in your output."
        )
        prompt = f"Chunks:\n\n{chunk_block}"
        response = self._client.models.generate_content(
            model=RESEARCH_SECTION_MODEL,
            contents=[
                genai_types.Content(role="user", parts=[genai_types.Part(text=prompt)]),
            ],
            config=genai_types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.3,
            ),
        )
        meta = response.usage_metadata
        in_tok = int(getattr(meta, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(meta, "candidates_token_count", 0) or 0)
        return ChatResult(
            content=response.text or "",
            usage=Usage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                model_used=RESEARCH_SECTION_MODEL,
                cost_usd=calculate_cost(RESEARCH_SECTION_MODEL, in_tok, out_tok),
            ),
        )

    def generate_research_stitch(
        self,
        *,
        question: str,
        sections_markdown: str,
        citation_table: str,
        expected_gaps: Sequence[str],
    ) -> ChatResult:
        """Stitch globalized section drafts into a final report (Pro model).

        sections_markdown already has globalized [n] citations.
        citation_table is a numbered reference list shown at the end of the
        prompt so the model can see where each [n] points to.
        """
        gaps_block = (
            "\n".join(f"- {g}" for g in expected_gaps) if expected_gaps else "(none listed)"
        )
        has_citations = bool(citation_table.strip())
        if has_citations:
            system = (
                "You are finalizing a research report. Each [n] citation token in the "
                "section drafts refers to one of the sources in the Citations table. "
                "Write: (1) a 3-5 sentence TL;DR at the top under a '## TL;DR' heading, "
                "(2) light connective prose between sections so they flow as one report "
                "(keep each section's existing heading and body verbatim where possible), "
                "(3) a final '## Open questions' section listing gaps the corpus does not "
                "cover. PRESERVE every existing [n] citation token verbatim. DO NOT "
                "introduce new citation numbers. DO NOT renumber anything. Output is the "
                "full report markdown."
            )
            prompt = (
                f"Question: {question}\n\n"
                f"Expected gaps the planner flagged:\n{gaps_block}\n\n"
                f"--- SECTION DRAFTS (citations already globalized) ---\n"
                f"{sections_markdown}\n"
                f"--- END SECTION DRAFTS ---\n\n"
                f"--- CITATIONS ---\n"
                f"{citation_table}\n"
                f"--- END CITATIONS ---"
            )
        else:
            # Knowledge-only mode: no source corpus, no citations. Don't mention
            # citations or sources in the prompt -- the model will mirror that
            # language back into the prose as disclaimers.
            system = (
                "You are finalizing a research report drawn from your general "
                "knowledge (no external source corpus). Write: (1) a 3-5 sentence "
                "TL;DR at the top under a '## TL;DR' heading, (2) light connective "
                "prose between the section drafts so they flow as one report "
                "(keep each section's existing heading and body verbatim where "
                "possible), (3) a final '## Open questions' section listing gaps "
                "or follow-up angles a reader might want. Do NOT include any [n] "
                "citation tokens. Do NOT apologize, disclaim, or mention that "
                "sources were not provided -- write the report directly as a "
                "confident, informative answer."
            )
            prompt = (
                f"Question: {question}\n\n"
                f"Expected gaps the planner flagged:\n{gaps_block}\n\n"
                f"--- SECTION DRAFTS ---\n"
                f"{sections_markdown}\n"
                f"--- END SECTION DRAFTS ---"
            )
        response = self._client.models.generate_content(
            model=RESEARCH_STITCH_MODEL,
            contents=[
                genai_types.Content(role="user", parts=[genai_types.Part(text=prompt)]),
            ],
            config=genai_types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.3,
            ),
        )
        meta = response.usage_metadata
        in_tok = int(getattr(meta, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(meta, "candidates_token_count", 0) or 0)
        return ChatResult(
            content=response.text or "",
            usage=Usage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                model_used=RESEARCH_STITCH_MODEL,
                cost_usd=calculate_cost(RESEARCH_STITCH_MODEL, in_tok, out_tok),
            ),
        )

    def generate_summary(self, source_text: str, *, max_chars: int = 12000) -> ChatResult:
        """One-shot source summary used during ingestion."""
        truncated = source_text[:max_chars]
        prompt = (
            "Summarize this source in 2 concise sentences. "
            "Then list 3-5 key topics (each <=4 words). "
            "Then suggest 3 questions a reader might ask. "
            'Return ONLY valid JSON with keys: "summary", "topics", "suggested_questions". '
            "No markdown fences, no commentary.\n\n"
            f"---\n{truncated}\n---"
        )
        response = self._client.models.generate_content(
            model=SUMMARY_MODEL,
            contents=[
                genai_types.Content(role="user", parts=[genai_types.Part(text=prompt)]),
            ],
            config=genai_types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        meta = response.usage_metadata
        in_tok = int(getattr(meta, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(meta, "candidates_token_count", 0) or 0)
        return ChatResult(
            content=response.text or "",
            usage=Usage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                model_used=SUMMARY_MODEL,
                cost_usd=calculate_cost(SUMMARY_MODEL, in_tok, out_tok),
            ),
        )


_service: GeminiService | None = None


def get_gemini() -> GeminiService:
    global _service
    if _service is None:
        _service = GeminiService()
    return _service


# ----- Helpers (module-private) -----

def _pcm_to_wav(pcm: bytes) -> bytes:
    """Wrap raw PCM16 mono 24kHz bytes in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(TTS_CHANNELS)
        wf.setsampwidth(TTS_SAMPLE_WIDTH)
        wf.setframerate(TTS_SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


_STUDY_INSTRUCTIONS: dict[str, str] = {
    "flashcards": (
        "Generate exactly 20 flashcards covering the most important facts and "
        "concepts in the source material below. Each flashcard MUST have a "
        "concise 'front' (a question, term, or prompt) and a 'back' "
        "(the answer or explanation). Return ONLY JSON with this exact shape:\n"
        '{"flashcards":[{"front":"...","back":"..."}]}'
    ),
    "quiz": (
        "Generate exactly 10 multiple-choice quiz questions from the source "
        "material below. Each question MUST have 4 options (one correct). "
        "Provide a brief 'explanation' justifying the correct answer. Return "
        "ONLY JSON with this exact shape:\n"
        '{"questions":[{"q":"...","options":["a","b","c","d"],'
        '"correct_index":0,"explanation":"..."}]}'
    ),
    "study_guide": (
        "Generate a structured study guide from the source material below. "
        "Include 4-7 learning objectives, 6-12 key concepts (each with a 1-2 "
        "sentence definition), a 4-6 sentence summary, and 5-8 review "
        "questions. Return ONLY JSON with this exact shape:\n"
        '{"objectives":["..."],'
        '"key_concepts":[{"name":"...","definition":"..."}],'
        '"summary":"...",'
        '"review_questions":["..."]}'
    ),
    "faq": (
        "Generate exactly 8 FAQs that a curious reader is most likely to ask "
        "about the source material below, with concise but complete answers. "
        "Return ONLY JSON with this exact shape:\n"
        '{"faqs":[{"q":"...","a":"..."}]}'
    ),
}


def _study_prompt(kind: str, context: str) -> str:
    instr = _STUDY_INSTRUCTIONS.get(kind)
    if not instr:
        raise ValueError(f"unknown study kind: {kind}")
    return (
        f"{instr}\n\n"
        "No commentary, no markdown fences, valid JSON only.\n\n"
        "--- SOURCES ---\n"
        f"{context}\n"
        "--- END SOURCES ---"
    )
