"""Deep research pipeline (Phase 3.a).

Tree-of-thought sectioned report:
  1. PLAN          gemini-3-flash-preview     -> outline (3-5 sections)
  2. PER-SECTION   gemini-3-flash-preview * N -> embed sub_query, retrieve top-k chunks,
                                                 draft section markdown with local [n] citations
  3. STITCH        gemini-3.1-pro-preview     -> TL;DR + connective prose + "Open questions"
                                                 over server-side globalized citations

Runs detached as a FastAPI BackgroundTask. Vercel 300s ceiling enforced via
per-stage asyncio.wait_for timeouts and a total-section-budget cap.

Failure modes:
- Plan returns invalid/empty -> status='failed'
- A section fails after one retry -> mark that section 'failed', continue
- All sections fail -> status='failed' (skip stitch)
- Stitch fails -> status='failed'
- Some sections succeed, others failed -> status='partial' (stitch over survivors)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from app.schemas.research import Plan, SectionCitation, SectionDraft
from app.services.gemini import (
    RESEARCH_PLAN_MODEL,
    RESEARCH_SECTION_MODEL,
    RESEARCH_STITCH_MODEL,
    GroundingHit,
    GroundingSupport,
    get_gemini,
)
from app.services.rag import CITATION_RE, RetrievedChunk, retrieve
from app.services.supabase_client import get_supabase
from app.services.usage import log_usage

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Per-stage timeouts (seconds). Total worst-case budget = 30 + 150 + 120 = 300s,
# fits under Vercel function ceiling. Stitch gets the slack because Pro on
# 3-5 sections + grounded web citation table can drift past 90s.
PLAN_TIMEOUT = 30.0
SECTION_TIMEOUT = 45.0
SECTION_BUDGET_TOTAL = 150.0
STITCH_TIMEOUT = 120.0

# Retrieval budget per section.
SECTION_TOP_K = 8

# Sources passed to the planner (caps the prompt size).
PLAN_MAX_SOURCES = 20

# Stitch input dedup cap.
STITCH_MAX_CHUNKS = 30


@dataclass
class _SourceListing:
    name: str
    summary: str


def enqueue_research_job(
    *,
    notebook_id: str,
    user_id: str,
    session_id: str | None,
    question: str,
    source_ids: list[str] | None,
) -> dict:
    """Insert the ``research_reports`` row (status='pending') and return it.

    Caller is responsible for adding ``run_research_blocking`` to BackgroundTasks.
    Raises on unique-constraint violation (B-COR-02 / partial UNIQUE index).
    """
    sb = get_supabase()
    payload: dict[str, Any] = {
        "notebook_id": notebook_id,
        "user_id": user_id,
        "session_id": session_id,
        "question": question,
        "source_ids": source_ids or [],
        "status": "pending",
        "model_plan": RESEARCH_PLAN_MODEL,
        "model_sections": RESEARCH_SECTION_MODEL,
        "model_stitch": RESEARCH_STITCH_MODEL,
    }
    res = sb.table("research_reports").insert(payload).execute()
    if not res.data:
        raise RuntimeError("Failed to create research_reports row")
    return res.data[0]


def _mirror_failure_to_chat(report_id: str, error: str) -> None:
    """Replace the linked assistant chat_messages placeholder with a clear
    failure marker so the in-thread UI transitions out of 'Researching…'.

    Best-effort: never raises. Frontend reads ``content`` as markdown.
    """
    try:
        body = f"**Research failed.**\n\n{error}"
        get_supabase().table("chat_messages").update(
            {"content": body}
        ).eq("research_report_id", str(report_id)).eq(
            "role", "assistant"
        ).eq("content", "Researching…").execute()
    except Exception:  # noqa: BLE001 — mirror is best-effort
        log.exception(
            "research failure mirror failed report_id=%s", report_id
        )


def _mark(report_id: str, fields: dict) -> None:
    """Update research_reports row. Retries once on transient error (B-COR-04)."""
    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            get_supabase().table("research_reports").update(fields).eq(
                "id", report_id
            ).execute()
            if attempt == 2:
                log.warning("research._mark succeeded on retry report_id=%s", report_id)
            return
        except Exception as e:  # noqa: BLE001 — bare-except policy allows fire-and-forget DB retries
            last_exc = e
            if attempt == 1:
                time.sleep(0.5)
                continue
    log.error(
        "STUCK_ROW research._mark exhausted retries report_id=%s err=%s",
        report_id,
        str(last_exc)[:200],
    )


def _fetch_source_summaries(notebook_id: str, source_ids: list[str] | None) -> list[_SourceListing]:
    """Fetch (name, summary) for ready sources used to scope the plan prompt.

    Filters to source_ids subset if provided, else all ready sources in the notebook.
    """
    sb = get_supabase()
    q = (
        sb.table("sources")
        .select("id,name,source_guide")
        .eq("notebook_id", notebook_id)
        .eq("status", "ready")
    )
    if source_ids:
        q = q.in_("id", source_ids)
    res = q.execute()
    out: list[_SourceListing] = []
    for r in (res.data or []):
        guide = r.get("source_guide") or {}
        summary = str(guide.get("summary") or "")
        out.append(_SourceListing(name=str(r.get("name") or ""), summary=summary))
    return out[:PLAN_MAX_SOURCES]


def _globalize_citations(
    sections: list[SectionDraft],
) -> tuple[list[SectionDraft], list[dict]]:
    """Renumber per-section local [n] citations to a single global numbering.

    Returns (rewritten_sections, global_citation_dicts).
    Deduplicates by ``chunk_id`` -- a chunk cited in two sections gets one
    global number.
    """
    global_by_chunk: dict[str, dict] = {}  # chunk_id -> Citation dict (with global number)
    rewritten: list[SectionDraft] = []

    for section in sections:
        if section.status != "ready":
            rewritten.append(section)
            continue

        local_to_global: dict[int, int] = {}
        for cite in section.citations:
            if cite.chunk_id in global_by_chunk:
                # Already assigned a global number.
                global_n = global_by_chunk[cite.chunk_id]["number"]
            else:
                global_n = len(global_by_chunk) + 1
                global_by_chunk[cite.chunk_id] = {
                    "number": global_n,
                    "chunk_id": cite.chunk_id,
                    "source_id": cite.source_id,
                    "source_name": cite.source_name,
                    "text_excerpt": cite.text_excerpt,
                    "metadata": cite.metadata,
                    "similarity": cite.similarity,
                }
            local_to_global[cite.number] = global_n

        # Rewrite all [n] tokens in section's content_md.
        def _replace(match: re.Match[str], _map: dict[int, int] = local_to_global) -> str:
            n = int(match.group(1))
            g = _map.get(n)
            return f"[{g}]" if g is not None else ""

        new_md = CITATION_RE.sub(_replace, section.content_md)
        # Rewrite citation numbers in the section's citation list too.
        new_cites = [
            SectionCitation(
                number=local_to_global.get(c.number, c.number),
                chunk_id=c.chunk_id,
                source_id=c.source_id,
                source_name=c.source_name,
                text_excerpt=c.text_excerpt,
                metadata=c.metadata,
                similarity=c.similarity,
            )
            for c in section.citations
        ]
        rewritten.append(
            SectionDraft(
                title=section.title,
                sub_query=section.sub_query,
                content_md=new_md,
                citations=new_cites,
                status="ready",
                error=None,
            )
        )

    # Stable sort by global number.
    global_list = sorted(global_by_chunk.values(), key=lambda d: d["number"])
    return rewritten, global_list


def _strip_unresolved_citations(text: str, global_count: int) -> str:
    """Drop any [n] token whose n exceeds the global citation count."""
    def _check(m: re.Match[str]) -> str:
        n = int(m.group(1))
        if 1 <= n <= global_count:
            return m.group(0)
        log.warning("research stitch dropped unresolved citation [%d]", n)
        return ""

    return CITATION_RE.sub(_check, text)


def _build_citation_table(global_citations: list[dict]) -> str:
    """Render the citation reference table for the stitch prompt."""
    lines = []
    for c in global_citations:
        lines.append(f"[{c['number']}] {c['source_name']}: {c['text_excerpt']}")
    return "\n".join(lines)


def _join_sections_markdown(sections: list[SectionDraft]) -> str:
    """Concatenate ready sections as `## {title}\n\n{content_md}` blocks."""
    parts = []
    for s in sections:
        if s.status != "ready":
            continue
        parts.append(f"## {s.title}\n\n{s.content_md.strip()}")
    return "\n\n".join(parts)


async def _run_section(
    *,
    question: str,
    notebook_id: str,
    section_index: int,
    title: str,
    sub_query: str,
    source_ids: list[str] | None,
) -> SectionDraft:
    """Embed sub_query -> retrieve -> draft section. One retry on Gemini error."""
    gemini = get_gemini()

    # Embed sub_query (gotcha #1: _embed iterates per-text under the hood).
    embed = await asyncio.to_thread(lambda: gemini.embed_query(sub_query))
    if not embed.vectors:
        return SectionDraft(
            title=title,
            sub_query=sub_query,
            content_md="",
            status="failed",
            error="empty embedding for sub_query",
        )
    qvec = embed.vectors[0]

    chunks = await retrieve(
        notebook_id=notebook_id,
        query_vector=qvec,
        source_ids=source_ids,
        k=SECTION_TOP_K,
    )
    # Diagnostic: lets us tell "knowledge-only because no sources" apart from
    # "knowledge-only because retrieval missed" when a user reports "no
    # sources" but the notebook is populated.
    log.info(
        "research section %d retrieved %d chunks (notebook_id=%s, "
        "source_ids_filter=%s, sub_query=%r, source_diversity=%d)",
        section_index,
        len(chunks),
        notebook_id,
        source_ids,
        sub_query[:120],
        len({c.source_id for c in chunks}),
    )

    # Knowledge-only path: empty corpus (sourceless notebook) OR no chunks
    # matched the sub_query embedding. Draft the section with Gemini's
    # google_search grounding so the report still carries real web citations.
    if not chunks:
        last_exc: Exception | None = None
        last_empty: bool = False
        for attempt in (1, 2):
            try:
                cr, hits, supports = await asyncio.to_thread(
                    lambda: gemini.generate_research_section_knowledge(
                        question=question,
                        title=title,
                        sub_query=sub_query,
                    )
                )
                section_md = (cr.content or "").strip()
                if section_md:
                    section_md, web_citations = _inject_grounding_citations(
                        section_md, hits, supports,
                    )
                    log.info(
                        "research knowledge-only section %d grounded: "
                        "%d hits, %d supports, %d web citations",
                        section_index,
                        len(hits),
                        len(supports),
                        len(web_citations),
                    )
                    return SectionDraft(
                        title=title,
                        sub_query=sub_query,
                        content_md=section_md,
                        citations=web_citations,
                        status="ready",
                        error=None,
                    )
                last_empty = True
                if attempt == 1:
                    log.warning(
                        "research knowledge-only section %d empty content, retrying",
                        section_index,
                    )
                    await asyncio.sleep(0.5)
                    continue
            except Exception as e:  # noqa: BLE001 — retry once on Gemini exception (B-COR-04)
                last_exc = e
                last_empty = False
                if attempt == 1:
                    log.warning(
                        "research knowledge-only section %d retrying: %s",
                        section_index,
                        str(e)[:200],
                    )
                    await asyncio.sleep(0.5)
                    continue
        # Both attempts produced empty content -> return a partial section
        # rather than failing it outright, so the stitch step still has at
        # least minimal text to work with and the pipeline doesn't cascade
        # into 'all sections failed'.
        if last_empty:
            placeholder = (
                f"_The model returned no content for the angle "
                f'"{sub_query}". This section is intentionally minimal._'
            )
            return SectionDraft(
                title=title,
                sub_query=sub_query,
                content_md=placeholder,
                citations=[],
                status="ready",
                error=None,
            )
        return SectionDraft(
            title=title,
            sub_query=sub_query,
            content_md="",
            status="failed",
            error=f"knowledge-only section failed: {str(last_exc)[:300]}",
        )

    # Sourced path: retrieve hit, draft section grounded in chunks with [n] citations.
    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            cr = await asyncio.to_thread(
                lambda: gemini.generate_research_section(
                    question=question,
                    title=title,
                    chunks=[
                        {"source_name": c.source_name, "content": c.content}
                        for c in chunks
                    ],
                )
            )
            section_md = (cr.content or "").strip()
            if not section_md:
                raise RuntimeError("empty section content")
            citations = _parse_local_citations(section_md, chunks)
            # Fallback: section was sourced (retrieve returned chunks) but the
            # model emitted no [n] tokens. Surface all retrieved chunks as
            # citations so the UI still shows source pills + a footnote list.
            # Otherwise users see an empty 'Knowledge-only report' state for
            # what should be a sourced section.
            if not citations and chunks:
                log.info(
                    "research section %d had %d retrieved chunks but emitted "
                    "no [n] tokens; falling back to all-chunks attribution",
                    section_index,
                    len(chunks),
                )
                citations = [
                    SectionCitation(
                        number=i + 1,
                        chunk_id=c.chunk_id,
                        source_id=c.source_id,
                        source_name=c.source_name,
                        text_excerpt=c.content[:300]
                        + ("…" if len(c.content) > 300 else ""),
                        metadata=c.metadata,
                        similarity=c.similarity,
                    )
                    for i, c in enumerate(chunks)
                ]
            return SectionDraft(
                title=title,
                sub_query=sub_query,
                content_md=section_md,
                citations=citations,
                status="ready",
                error=None,
            )
        except Exception as e:  # noqa: BLE001 — retry once on any Gemini-side error (B-COR-04)
            last_exc = e
            if attempt == 1:
                log.warning(
                    "research section %d retrying after error: %s",
                    section_index,
                    str(e)[:200],
                )
                await asyncio.sleep(0.5)
                continue

    return SectionDraft(
        title=title,
        sub_query=sub_query,
        content_md="",
        status="failed",
        error=f"section generation failed: {str(last_exc)[:300]}",
    )


def _stable_web_chunk_id(uri: str) -> str:
    """Deterministic ``chunk_id`` for a web grounding URI.

    Matches the ``_globalize_citations`` dedup key so that two sections that
    both cite the same URL collapse to a single global citation.
    """
    return "web:" + hashlib.sha1(uri.encode("utf-8")).hexdigest()[:16]


def _domain_of(uri: str) -> str:
    """Best-effort netloc extractor for the citation pill label and metadata."""
    try:
        return urlparse(uri).netloc or uri
    except Exception:  # noqa: BLE001 — defensive parsing
        return uri


def _inject_grounding_citations(
    text: str,
    hits: list[GroundingHit],
    supports: list[GroundingSupport],
) -> tuple[str, list[SectionCitation]]:
    """Splice ``[n]`` tokens into knowledge-only section markdown and build citations.

    - Deduplicates hits by URI (first-seen order keeps numbering stable).
    - Inserts citation tokens at each support's ``end_index`` (UTF-8 byte
      offset per Gemini grounding spec), walking supports in reverse so
      earlier insertions don't shift later offsets.
    - When a support points at multiple hits, tokens are appended in the
      support's ``hit_indices`` order; duplicate hit numbers within one
      support are collapsed.
    - Returns ``(text, [])`` unchanged when grounding is empty so the caller
      degrades gracefully to "real knowledge-only".
    """
    if not hits or not supports:
        return text, []

    # First pass: walk supports in order to assign each unique URI a stable
    # 1-based citation number and grab a snippet for the footnote excerpt.
    seen_uris: dict[str, int] = {}
    citations: list[SectionCitation] = []
    for sup in supports:
        for raw_idx in sup.hit_indices:
            if raw_idx < 0 or raw_idx >= len(hits):
                continue
            hit = hits[raw_idx]
            if not hit.uri or hit.uri in seen_uris:
                continue
            n = len(seen_uris) + 1
            seen_uris[hit.uri] = n
            domain = _domain_of(hit.uri)
            excerpt = (sup.text_segment or "")[:300]
            citations.append(
                SectionCitation(
                    number=n,
                    chunk_id=_stable_web_chunk_id(hit.uri),
                    source_id=_stable_web_chunk_id(hit.uri),
                    source_name=hit.title or domain or hit.uri,
                    text_excerpt=excerpt,
                    metadata={
                        "type": "web",
                        "url": hit.uri,
                        "domain": domain,
                    },
                    similarity=float(sup.confidence),
                )
            )

    if not citations:
        return text, []

    # Second pass: inject [n] tokens at byte offsets, reverse end_index order
    # so earlier insertions don't shift later offsets.
    encoded = text.encode("utf-8")
    for sup in sorted(supports, key=lambda s: s.end_index, reverse=True):
        if sup.end_index < 0 or sup.end_index > len(encoded):
            continue
        markers: list[str] = []
        seen_in_this: set[int] = set()
        for raw_idx in sup.hit_indices:
            if raw_idx < 0 or raw_idx >= len(hits):
                continue
            uri = hits[raw_idx].uri
            n = seen_uris.get(uri)
            if n is None or n in seen_in_this:
                continue
            seen_in_this.add(n)
            markers.append(f"[{n}]")
        if not markers:
            continue
        marker_bytes = "".join(markers).encode("utf-8")
        encoded = encoded[: sup.end_index] + marker_bytes + encoded[sup.end_index:]

    return encoded.decode("utf-8", errors="replace"), citations


def _parse_local_citations(
    text: str, chunks: list[RetrievedChunk]
) -> list[SectionCitation]:
    """Parse [n] tokens against the section's chunk list, dedupe, drop out-of-range."""
    seen: set[int] = set()
    out: list[SectionCitation] = []
    for m in CITATION_RE.finditer(text):
        n = int(m.group(1))
        if n in seen:
            continue
        if n < 1 or n > len(chunks):
            continue
        seen.add(n)
        c = chunks[n - 1]
        excerpt = c.content[:300] + ("…" if len(c.content) > 300 else "")
        out.append(
            SectionCitation(
                number=n,
                chunk_id=c.chunk_id,
                source_id=c.source_id,
                source_name=c.source_name,
                text_excerpt=excerpt,
                metadata=c.metadata,
                similarity=c.similarity,
            )
        )
    return out


async def _run_research_async(report_id: str) -> None:
    """Main orchestrator. Status transitions + partial-success handling."""
    sb = get_supabase()

    row_res = (
        sb.table("research_reports")
        .select("*")
        .eq("id", report_id)
        .limit(1)
        .execute()
    )
    if not row_res.data:
        log.error("research row %s not found", report_id)
        return

    row = row_res.data[0]
    user_id = row["user_id"]
    notebook_id = row["notebook_id"]
    question = row["question"]
    source_ids = list(row.get("source_ids") or []) or None

    _mark(report_id, {"status": "researching"})

    gemini = get_gemini()
    total_in_tok = 0
    total_out_tok = 0
    total_cost = 0.0

    # ---- Stage 1: plan ----
    # Empty source_listings is fine: the pipeline runs in knowledge-only mode
    # and produces a report with no citations. The plan helper handles both
    # cases via its prompt branch.
    try:
        source_listings = await asyncio.to_thread(
            _fetch_source_summaries, notebook_id, source_ids
        )
        log.info(
            "research plan input: notebook_id=%s, source_ids_filter=%s, "
            "source_listings_count=%d",
            notebook_id,
            source_ids,
            len(source_listings),
        )

        plan_raw, plan_usage = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: gemini.generate_research_plan(
                    question=question,
                    source_summaries=[
                        {"name": s.name, "summary": s.summary} for s in source_listings
                    ],
                )
            ),
            timeout=PLAN_TIMEOUT,
        )
        # Gemini sometimes wraps JSON-strict output in a 1-element list even
        # when the schema asks for an object. Unwrap defensively before validation.
        if isinstance(plan_raw, list) and len(plan_raw) == 1 and isinstance(plan_raw[0], dict):
            plan_raw = plan_raw[0]
        try:
            plan = Plan.model_validate(plan_raw)
        except ValidationError as e:
            raise RuntimeError(f"plan failed validation: {e.errors()}") from e
        if len(plan.sections) > 5:
            plan.sections = plan.sections[:5]

        total_in_tok += plan_usage.usage.input_tokens
        total_out_tok += plan_usage.usage.output_tokens
        total_cost += plan_usage.usage.cost_usd or 0.0

        _mark(report_id, {"plan": plan.model_dump()})

        log_usage(
            user_id=user_id,
            notebook_id=notebook_id,
            operation_type="research_plan",
            usage=plan_usage.usage,
            metadata={"report_id": report_id},
        )
    except asyncio.TimeoutError:
        log.warning("research plan timed out report_id=%s", report_id)
        err = f"plan step timed out after {int(PLAN_TIMEOUT)}s"
        _mark(
            report_id,
            {
                "status": "failed",
                "error": err,
                "completed_at": _now_iso(),
            },
        )
        _mirror_failure_to_chat(report_id, err)
        return
    except Exception as e:  # noqa: BLE001
        log.exception("research plan failed report_id=%s", report_id)
        err = f"plan step failed: {str(e)[:300]}"
        _mark(
            report_id,
            {
                "status": "failed",
                "error": err,
                "completed_at": _now_iso(),
            },
        )
        _mirror_failure_to_chat(report_id, err)
        return

    # ---- Stage 2: per-section (sequential, gotcha #3 thread-local httpx) ----
    drafts: list[SectionDraft] = []
    section_budget_started = time.monotonic()
    for idx, ps in enumerate(plan.sections):
        elapsed = time.monotonic() - section_budget_started
        if elapsed >= SECTION_BUDGET_TOTAL:
            log.warning(
                "research section budget exhausted at section %d for report_id=%s",
                idx,
                report_id,
            )
            drafts.append(
                SectionDraft(
                    title=ps.title,
                    sub_query=ps.sub_query,
                    content_md="",
                    status="failed",
                    error="section budget exhausted before this section started",
                )
            )
            continue

        try:
            draft = await asyncio.wait_for(
                _run_section(
                    question=question,
                    notebook_id=notebook_id,
                    section_index=idx,
                    title=ps.title,
                    sub_query=ps.sub_query,
                    source_ids=source_ids,
                ),
                timeout=SECTION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log.warning(
                "research section %d timed out report_id=%s timeout=%.0fs",
                idx,
                report_id,
                SECTION_TIMEOUT,
            )
            draft = SectionDraft(
                title=ps.title,
                sub_query=ps.sub_query,
                content_md="",
                status="failed",
                error=f"section timed out after {int(SECTION_TIMEOUT)}s",
            )

        drafts.append(draft)
        # Persist incremental section progress so polling clients see state.
        _mark(
            report_id,
            {"sections": [d.model_dump() for d in drafts]},
        )

    ready_drafts = [d for d in drafts if d.status == "ready"]
    if not ready_drafts:
        err = "all sections failed"
        _mark(
            report_id,
            {
                "status": "failed",
                "sections": [d.model_dump() for d in drafts],
                "error": err,
                "completed_at": _now_iso(),
            },
        )
        _mirror_failure_to_chat(report_id, err)
        return

    # ---- Stage 3: pre-stitch globalize -> Pro stitch ----
    rewritten, global_citations = _globalize_citations(drafts)
    # Re-key into ready vs failed: globalize leaves failed sections as-is.
    sections_md = _join_sections_markdown(rewritten)
    citation_table = _build_citation_table(global_citations[:STITCH_MAX_CHUNKS])

    try:
        stitch_cr = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: gemini.generate_research_stitch(
                    question=question,
                    sections_markdown=sections_md,
                    citation_table=citation_table,
                    expected_gaps=list(plan.expected_gaps),
                )
            ),
            timeout=STITCH_TIMEOUT,
        )
    except (asyncio.TimeoutError, Exception) as stitch_err:  # noqa: BLE001 — single fallback path
        is_timeout = isinstance(stitch_err, asyncio.TimeoutError)
        if is_timeout:
            log.warning("research stitch timed out report_id=%s", report_id)
            err = f"stitch step timed out after {int(STITCH_TIMEOUT)}s; serving raw sections"
        else:
            log.exception("research stitch failed report_id=%s", report_id)
            err = f"stitch step failed: {str(stitch_err)[:300]}; serving raw sections"

        # Fallback: surface the drafted sections + global citations as a
        # partial report instead of losing them. The user already paid for
        # plan + section generation; they get a readable (unstitched)
        # document rather than a "failed" toast.
        ready_sections = [d for d in rewritten if d.status == "ready"]
        if ready_sections:
            fallback_md = "## " + question.strip().rstrip("?") + "?\n\n"
            for d in ready_sections:
                fallback_md += f"## {d.title}\n\n{d.content_md.strip()}\n\n"
            fallback_md = _strip_unresolved_citations(fallback_md, len(global_citations))
            _mark(
                report_id,
                {
                    "status": "partial",
                    "sections": [d.model_dump() for d in rewritten],
                    "content_md": fallback_md,
                    "citations": global_citations,
                    "input_tokens": int(total_in_tok),
                    "output_tokens": int(total_out_tok),
                    "cost_usd": round(total_cost, 6),
                    "error": err,
                    "completed_at": _now_iso(),
                },
            )
            # Mirror fallback to chat_messages so the in-thread card shows
            # the partial report instead of "Research failed".
            try:
                source_ids_used = sorted(
                    {c.get("source_id") for c in global_citations if c.get("source_id")}
                )
                get_supabase().table("chat_messages").update(
                    {
                        "content": fallback_md,
                        "citations": global_citations,
                        "source_ids_used": source_ids_used,
                        "input_tokens": int(total_in_tok),
                        "output_tokens": int(total_out_tok),
                        "cost_usd": round(total_cost, 6),
                    }
                ).eq("research_report_id", str(report_id)).eq("role", "assistant").execute()
            except Exception:  # noqa: BLE001 — mirror is best-effort
                log.exception(
                    "research chat_messages mirror failed (stitch-fallback) "
                    "report_id=%s",
                    report_id,
                )
            return

        # No ready sections to surface -> genuine failure.
        _mark(
            report_id,
            {
                "status": "failed",
                "sections": [d.model_dump() for d in rewritten],
                "error": err,
                "completed_at": _now_iso(),
            },
        )
        _mirror_failure_to_chat(report_id, err)
        return

    final_md = _strip_unresolved_citations(stitch_cr.content or "", len(global_citations))

    total_in_tok += stitch_cr.usage.input_tokens
    total_out_tok += stitch_cr.usage.output_tokens
    total_cost += stitch_cr.usage.cost_usd or 0.0

    final_status = "ready" if all(d.status == "ready" for d in drafts) else "partial"
    _mark(
        report_id,
        {
            "status": final_status,
            "sections": [d.model_dump() for d in rewritten],
            "content_md": final_md,
            "citations": global_citations,
            "input_tokens": int(total_in_tok),
            "output_tokens": int(total_out_tok),
            "cost_usd": round(total_cost, 6),
            "completed_at": _now_iso(),
        },
    )

    # Mirror the final report onto the linked assistant chat_messages row so
    # the in-thread chat UI shows the report on reload / when the polled
    # report query has been garbage collected. Best-effort; a failure here
    # does not flip research_reports.status back to failed.
    try:
        source_ids_used = sorted(
            {c.get("source_id") for c in global_citations if c.get("source_id")}
        )
        get_supabase().table("chat_messages").update(
            {
                "content": final_md,
                "citations": global_citations,
                "source_ids_used": source_ids_used,
                "input_tokens": int(total_in_tok),
                "output_tokens": int(total_out_tok),
                "cost_usd": round(total_cost, 6),
            }
        ).eq("research_report_id", str(report_id)).eq("role", "assistant").execute()
    except Exception:  # noqa: BLE001 — mirror is best-effort
        log.exception(
            "research chat_messages mirror failed report_id=%s "
            "(research_reports row already ready)",
            report_id,
        )

    log_usage(
        user_id=user_id,
        notebook_id=notebook_id,
        operation_type="research_stitch",
        usage=stitch_cr.usage,
        metadata={"report_id": report_id},
    )


def run_research_blocking(report_id: str) -> None:
    """Sync wrapper for FastAPI BackgroundTasks."""
    asyncio.run(_run_research_async(report_id))
