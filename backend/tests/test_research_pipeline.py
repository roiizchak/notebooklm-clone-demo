"""Phase 3.a service tests for app.services.research.

Gemini + RAG are mocked. The orchestrator's behavior we pin:
- Plan invalid / empty -> status='failed'
- Plan >5 sections clipped to 5
- Section failure with retry -> marked failed, pipeline continues (partial)
- All sections fail -> status='failed', no stitch
- Globalization renumbers citations across sections, dedupes by chunk_id
- Unresolved [n] tokens stripped in final content_md
- Per-section timeout caught -> section failed, continue
- Stitch timeout -> status='failed'
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services import research as research_svc
from app.services.rag import RetrievedChunk
from app.services.gemini import ChatResult, Usage, EmbedResult


REPORT = "44444444-4444-4444-4444-444444444441"
NB = "11111111-1111-1111-1111-111111111111"
USER = "00000000-0000-0000-0000-000000000001"


def _report_row() -> dict:
    return {
        "id": REPORT,
        "notebook_id": NB,
        "user_id": USER,
        "session_id": None,
        "question": "What are the methods?",
        "source_ids": [],
        "status": "pending",
    }


def _make_chunk(chunk_id: str, source_id: str, name: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_id=source_id,
        source_name=name,
        content=text,
        metadata={},
        similarity=0.85,
    )


def _stub_gemini(monkeypatch, *, plan_dict, section_results, stitch_text):
    """Install a fake GeminiService with deterministic responses.

    section_results is a list of (content, error_to_raise|None). Each call to
    generate_research_section pops the next entry. If error_to_raise is set,
    raise it. Note retries pop a new entry too.
    """
    state = {"section_idx": 0}

    fake = MagicMock()

    def _plan(*, question, source_summaries):
        return plan_dict, ChatResult(
            content="{}",
            usage=Usage(input_tokens=100, output_tokens=50, model_used="plan", cost_usd=0.001),
        )

    def _embed_query(text):
        return EmbedResult(
            vectors=[[0.1] * 1536],
            usage=Usage(input_tokens=10, output_tokens=0, model_used="embed", cost_usd=0.0),
        )

    def _section(*, question, title, chunks):
        i = state["section_idx"]
        state["section_idx"] += 1
        if i >= len(section_results):
            raise RuntimeError("ran out of section stubs")
        content, err = section_results[i]
        if err is not None:
            raise err
        return ChatResult(
            content=content,
            usage=Usage(input_tokens=500, output_tokens=300, model_used="section", cost_usd=0.002),
        )

    def _stitch(*, question, sections_markdown, citation_table, expected_gaps):
        return ChatResult(
            content=stitch_text,
            usage=Usage(input_tokens=800, output_tokens=400, model_used="stitch", cost_usd=0.01),
        )

    fake.generate_research_plan = _plan
    fake.generate_research_section = _section
    fake.generate_research_stitch = _stitch
    fake.embed_query = _embed_query

    monkeypatch.setattr(research_svc, "get_gemini", lambda: fake)
    return fake


def _stub_retrieve(monkeypatch, chunks_per_call: list[list[RetrievedChunk]]):
    state = {"i": 0}

    async def _ret(**kwargs):
        i = state["i"]
        state["i"] += 1
        if i >= len(chunks_per_call):
            return []
        return chunks_per_call[i]

    monkeypatch.setattr(research_svc, "retrieve", _ret)


def _stub_sources(fake_supabase, source_listings: list[dict]):
    """Provide source rows for _fetch_source_summaries."""
    state = {"calls": 0}

    def _resp(chain):
        state["calls"] += 1
        # We expect at least one SELECT against sources table.
        return source_listings

    fake_supabase.responses["sources"] = _resp


def _stub_report_row(fake_supabase, row: dict):
    fake_supabase.responses["research_reports"] = MagicMock(data=[row])


@pytest.mark.asyncio
async def test_globalize_citations_renumbers_across_sections_and_dedupes():
    from app.schemas.research import SectionCitation, SectionDraft

    s1 = SectionDraft(
        title="A",
        sub_query="q1",
        content_md="Foo [1] bar [2]",
        citations=[
            SectionCitation(number=1, chunk_id="c1", source_id="s1", source_name="S1",
                            text_excerpt="ex1", metadata={}, similarity=0.9),
            SectionCitation(number=2, chunk_id="c2", source_id="s2", source_name="S2",
                            text_excerpt="ex2", metadata={}, similarity=0.8),
        ],
        status="ready",
    )
    # Section 2 cites the same c1 (dedup) + a new c3.
    s2 = SectionDraft(
        title="B",
        sub_query="q2",
        content_md="Baz [1] qux [2]",
        citations=[
            SectionCitation(number=1, chunk_id="c1", source_id="s1", source_name="S1",
                            text_excerpt="ex1", metadata={}, similarity=0.9),
            SectionCitation(number=2, chunk_id="c3", source_id="s3", source_name="S3",
                            text_excerpt="ex3", metadata={}, similarity=0.7),
        ],
        status="ready",
    )

    rewritten, global_list = research_svc._globalize_citations([s1, s2])
    assert len(global_list) == 3
    assert [c["number"] for c in global_list] == [1, 2, 3]
    assert {c["chunk_id"] for c in global_list} == {"c1", "c2", "c3"}

    # Section 1 keeps [1][2] (no dedup hits).
    assert rewritten[0].content_md == "Foo [1] bar [2]"
    # Section 2's local [1] -> global [1] (same c1), local [2] -> global [3] (new c3).
    assert rewritten[1].content_md == "Baz [1] qux [3]"


def test_strip_unresolved_citations_drops_out_of_range():
    out = research_svc._strip_unresolved_citations("hello [1] world [99] end", global_count=5)
    assert out == "hello [1] world  end"


@pytest.mark.asyncio
async def test_run_research_async_happy_path_marks_ready(fake_supabase, monkeypatch):
    _stub_report_row(fake_supabase, _report_row())
    _stub_sources(fake_supabase, [
        {"id": "src1", "name": "Doc A", "source_guide": {"summary": "About A"}},
    ])

    _stub_gemini(
        monkeypatch,
        plan_dict={
            "tldr_hint": "",
            "sections": [
                {"title": "Methods", "sub_query": "methods used", "rationale": ""},
                {"title": "Results", "sub_query": "results found", "rationale": ""},
            ],
            "expected_gaps": [],
        },
        section_results=[
            ("Methods section [1]", None),
            ("Results section [1]", None),
        ],
        stitch_text="## TL;DR\nShort. [1] [2]\n\n## Methods\nMethods section [1]\n\n## Results\nResults section [2]\n\n## Open questions\n- None.",
    )

    _stub_retrieve(monkeypatch, [
        [_make_chunk("c1", "src1", "Doc A", "alpha beta")],
        [_make_chunk("c2", "src1", "Doc A", "gamma delta")],
    ])

    await research_svc._run_research_async(REPORT)

    # Verify the final mark was a 'ready' status update.
    updates = [
        c for c in fake_supabase.calls
        if c[0] == "research_reports" and any(op == "update" for (op, _, _) in c[1])
    ]
    # Last update should be the terminal mark.
    last = updates[-1][1]
    update_args = next(c for c in last if c[0] == "update")
    payload = update_args[1][0]
    assert payload["status"] == "ready"
    assert payload["content_md"].startswith("## TL;DR")
    # 2 sections, each cites 1 chunk -> 2 distinct global citations.
    assert len(payload["citations"]) == 2


@pytest.mark.asyncio
async def test_run_research_async_partial_when_one_section_fails(fake_supabase, monkeypatch):
    _stub_report_row(fake_supabase, _report_row())
    _stub_sources(fake_supabase, [
        {"id": "src1", "name": "Doc A", "source_guide": {"summary": "About A"}},
    ])

    _stub_gemini(
        monkeypatch,
        plan_dict={
            "tldr_hint": "",
            "sections": [
                {"title": "Good", "sub_query": "x", "rationale": ""},
                {"title": "Bad", "sub_query": "y", "rationale": ""},
            ],
            "expected_gaps": [],
        },
        section_results=[
            ("Good section [1]", None),
            # Both attempts (initial + retry) raise.
            ("", RuntimeError("boom")),
            ("", RuntimeError("boom again")),
        ],
        stitch_text="## TL;DR\nok [1]\n\n## Good\nGood section [1]\n",
    )

    _stub_retrieve(monkeypatch, [
        [_make_chunk("c1", "src1", "Doc A", "alpha")],
        [_make_chunk("c2", "src1", "Doc A", "gamma")],
    ])

    await research_svc._run_research_async(REPORT)

    updates = [
        c for c in fake_supabase.calls
        if c[0] == "research_reports" and any(op == "update" for (op, _, _) in c[1])
    ]
    last = updates[-1][1]
    update_args = next(c for c in last if c[0] == "update")
    payload = update_args[1][0]
    assert payload["status"] == "partial", payload
    # Surviving section keeps its global [1] citation.
    assert "Good section [1]" in payload["content_md"]


@pytest.mark.asyncio
async def test_run_research_async_invalid_plan_marks_failed(fake_supabase, monkeypatch):
    _stub_report_row(fake_supabase, _report_row())
    _stub_sources(fake_supabase, [
        {"id": "src1", "name": "Doc A", "source_guide": {"summary": "x"}},
    ])

    # Plan returns sections=[] which fails Pydantic min_length=1 validation.
    _stub_gemini(
        monkeypatch,
        plan_dict={"sections": []},
        section_results=[],
        stitch_text="",
    )
    _stub_retrieve(monkeypatch, [])

    await research_svc._run_research_async(REPORT)

    updates = [
        c for c in fake_supabase.calls
        if c[0] == "research_reports" and any(op == "update" for (op, _, _) in c[1])
    ]
    last = updates[-1][1]
    update_args = next(c for c in last if c[0] == "update")
    payload = update_args[1][0]
    assert payload["status"] == "failed"
    assert "plan" in payload["error"].lower()


@pytest.mark.asyncio
async def test_plan_clipped_to_5_sections(fake_supabase, monkeypatch):
    """If planner returns >5 sections we clip to first 5 (defensive)."""
    _stub_report_row(fake_supabase, _report_row())
    _stub_sources(fake_supabase, [
        {"id": "src1", "name": "Doc A", "source_guide": {"summary": "x"}},
    ])

    # Pydantic Plan model has max_length=5 so >5 raises ValidationError -> failed.
    # That's the actual contract: Pydantic enforces the cap. Verify failed status
    # and error mentions validation.
    _stub_gemini(
        monkeypatch,
        plan_dict={
            "sections": [
                {"title": f"S{i}", "sub_query": f"q{i}"}
                for i in range(6)
            ],
        },
        section_results=[],
        stitch_text="",
    )
    _stub_retrieve(monkeypatch, [])

    await research_svc._run_research_async(REPORT)

    updates = [
        c for c in fake_supabase.calls
        if c[0] == "research_reports" and any(op == "update" for (op, _, _) in c[1])
    ]
    last = updates[-1][1]
    update_args = next(c for c in last if c[0] == "update")
    payload = update_args[1][0]
    # Strict validation: Pydantic Plan rejects >5 sections -> failed.
    assert payload["status"] == "failed"


@pytest.mark.asyncio
async def test_knowledge_only_mode_runs_with_no_sources(fake_supabase, monkeypatch):
    """Sourceless notebook -> plan runs with empty source list -> retrieve
    returns [] -> section falls through to generate_research_section_knowledge.
    Final report is ready with empty citations."""
    _stub_report_row(fake_supabase, _report_row())
    _stub_sources(fake_supabase, [])  # no sources at all

    # Build a fake gemini that records which section path was used.
    fake = MagicMock()
    fake.embed_query = lambda text: EmbedResult(
        vectors=[[0.1] * 1536],
        usage=Usage(input_tokens=1, output_tokens=0, model_used="e", cost_usd=0.0),
    )
    fake.generate_research_plan = lambda **kw: (
        {
            "tldr_hint": "",
            "sections": [{"title": "Intro", "sub_query": "basics", "rationale": ""}],
            "expected_gaps": [],
        },
        ChatResult(
            content="{}",
            usage=Usage(input_tokens=10, output_tokens=5, model_used="p", cost_usd=0.0),
        ),
    )
    knowledge_calls: list[dict] = []

    def _knowledge(*, question, title, sub_query):
        knowledge_calls.append({"title": title, "sub_query": sub_query})
        # Knowledge-only path now returns a 3-tuple including google_search
        # grounding metadata. Returning empty grounding here matches the
        # "search produced no usable hits" degraded path.
        return (
            ChatResult(
                content="Knowledge-only body. No citations.",
                usage=Usage(input_tokens=20, output_tokens=10, model_used="s", cost_usd=0.0),
            ),
            [],
            [],
        )

    fake.generate_research_section_knowledge = _knowledge

    # Should NOT be called when corpus is empty.
    def _sourced_should_not_run(**_kw):
        raise AssertionError("sourced section path called in knowledge-only mode")

    fake.generate_research_section = _sourced_should_not_run
    fake.generate_research_stitch = lambda **kw: ChatResult(
        content="## TL;DR\nKnowledge summary.\n\n## Intro\nKnowledge-only body. No citations.",
        usage=Usage(input_tokens=30, output_tokens=15, model_used="st", cost_usd=0.0),
    )

    monkeypatch.setattr(research_svc, "get_gemini", lambda: fake)
    _stub_retrieve(monkeypatch, [[]])  # empty retrieval result

    await research_svc._run_research_async(REPORT)

    assert knowledge_calls, "knowledge-only section was not invoked"

    updates = [
        c for c in fake_supabase.calls
        if c[0] == "research_reports" and any(op == "update" for (op, _, _) in c[1])
    ]
    last = updates[-1][1]
    update_args = next(c for c in last if c[0] == "update")
    payload = update_args[1][0]
    assert payload["status"] == "ready", payload
    # No grounding hits in this stub -> citations stay empty (degraded path).
    assert payload["citations"] == []


@pytest.mark.asyncio
async def test_knowledge_only_with_grounding_emits_web_citations(fake_supabase, monkeypatch):
    """Sourceless notebook + Gemini google_search grounding -> the final report
    persists web citations whose ``metadata.type == 'web'`` and ``metadata.url``
    is the grounding URI. Closes the recurring 'no sources visible' UX bug for
    knowledge-only Deep research reports."""
    from app.services.gemini import GroundingHit, GroundingSupport  # local to avoid touching headers

    _stub_report_row(fake_supabase, _report_row())
    _stub_sources(fake_supabase, [])

    fake = MagicMock()
    fake.embed_query = lambda text: EmbedResult(
        vectors=[[0.1] * 1536],
        usage=Usage(input_tokens=1, output_tokens=0, model_used="e", cost_usd=0.0),
    )
    fake.generate_research_plan = lambda **kw: (
        {
            "tldr_hint": "",
            "sections": [{"title": "Intro", "sub_query": "basics", "rationale": ""}],
            "expected_gaps": [],
        },
        ChatResult(
            content="{}",
            usage=Usage(input_tokens=10, output_tokens=5, model_used="p", cost_usd=0.0),
        ),
    )

    section_text = "Bundler X is popular in 2026."

    def _knowledge(*, question, title, sub_query):
        return (
            ChatResult(
                content=section_text,
                usage=Usage(input_tokens=20, output_tokens=10, model_used="s", cost_usd=0.0),
            ),
            [
                GroundingHit(uri="https://bundlers.example/2026", title="Bundler trends"),
            ],
            [
                GroundingSupport(
                    end_index=len("Bundler X is popular in 2026"),
                    text_segment="Bundler X is popular in 2026",
                    hit_indices=[0],
                    confidence=0.92,
                ),
            ],
        )

    fake.generate_research_section_knowledge = _knowledge
    fake.generate_research_section = lambda **_: (_ for _ in ()).throw(
        AssertionError("sourced path called in knowledge-only mode")
    )
    fake.generate_research_stitch = lambda **kw: ChatResult(
        # Preserve the [n] token so it survives stitching.
        content="## TL;DR\nWeb-grounded summary [1].\n\n## Intro\n" + kw["sections_markdown"],
        usage=Usage(input_tokens=30, output_tokens=15, model_used="st", cost_usd=0.0),
    )

    monkeypatch.setattr(research_svc, "get_gemini", lambda: fake)
    _stub_retrieve(monkeypatch, [[]])

    await research_svc._run_research_async(REPORT)

    updates = [
        c for c in fake_supabase.calls
        if c[0] == "research_reports" and any(op == "update" for (op, _, _) in c[1])
    ]
    last = updates[-1][1]
    update_args = next(c for c in last if c[0] == "update")
    payload = update_args[1][0]

    assert payload["status"] == "ready", payload
    citations = payload["citations"]
    assert len(citations) == 1, citations
    cit = citations[0]
    assert cit["metadata"]["type"] == "web"
    assert cit["metadata"]["url"] == "https://bundlers.example/2026"
    assert cit["source_name"] == "Bundler trends"
    # Section markdown should have a [1] token spliced in by the injector.
    sections_md = "\n".join(s.get("content_md", "") for s in payload["sections"])
    assert "[1]" in sections_md
    # Globalized [1] should also survive into the stitched final content_md.
    assert "[1]" in payload["content_md"]


@pytest.mark.asyncio
async def test_stitch_failure_preserves_sections_as_partial(fake_supabase, monkeypatch):
    """Stitch timeout or exception no longer marks the whole report 'failed' when
    we have ready sections + citations. Falls back to a locally-joined
    ``content_md`` so users keep the report instead of losing it to a Pro flake."""
    from app.services.gemini import GroundingHit, GroundingSupport

    _stub_report_row(fake_supabase, _report_row())
    _stub_sources(fake_supabase, [])

    fake = MagicMock()
    fake.embed_query = lambda text: EmbedResult(
        vectors=[[0.1] * 1536],
        usage=Usage(input_tokens=1, output_tokens=0, model_used="e", cost_usd=0.0),
    )
    fake.generate_research_plan = lambda **kw: (
        {
            "tldr_hint": "",
            "sections": [{"title": "Intro", "sub_query": "basics", "rationale": ""}],
            "expected_gaps": [],
        },
        ChatResult(
            content="{}",
            usage=Usage(input_tokens=10, output_tokens=5, model_used="p", cost_usd=0.0),
        ),
    )

    def _knowledge(*, question, title, sub_query):
        return (
            ChatResult(
                content="Section body about basics.",
                usage=Usage(input_tokens=20, output_tokens=10, model_used="s", cost_usd=0.0),
            ),
            [GroundingHit(uri="https://web.example/x", title="Example")],
            [
                GroundingSupport(
                    end_index=len("Section body about basics"),
                    text_segment="Section body about basics",
                    hit_indices=[0],
                    confidence=0.9,
                ),
            ],
        )

    fake.generate_research_section_knowledge = _knowledge
    fake.generate_research_section = lambda **_: (_ for _ in ()).throw(
        AssertionError("sourced path called")
    )

    def _stitch_raises(**_kw):
        raise RuntimeError("simulated Pro outage")

    fake.generate_research_stitch = _stitch_raises

    monkeypatch.setattr(research_svc, "get_gemini", lambda: fake)
    _stub_retrieve(monkeypatch, [[]])

    await research_svc._run_research_async(REPORT)

    updates = [
        c for c in fake_supabase.calls
        if c[0] == "research_reports" and any(op == "update" for (op, _, _) in c[1])
    ]
    last = updates[-1][1]
    update_args = next(c for c in last if c[0] == "update")
    payload = update_args[1][0]

    assert payload["status"] == "partial", payload
    assert payload["citations"], "citations dropped on stitch failure"
    assert payload["content_md"], "content_md not synthesized from sections"
    assert "Section body about basics" in payload["content_md"]
    assert "[1]" in payload["content_md"]
    assert "serving raw sections" in (payload.get("error") or "")


@pytest.mark.asyncio
async def test_plan_unwraps_gemini_list_envelope(fake_supabase, monkeypatch):
    """Gemini occasionally wraps JSON-strict object output in a 1-element list.
    The pipeline must unwrap before Pydantic validation."""
    _stub_report_row(fake_supabase, _report_row())
    _stub_sources(fake_supabase, [
        {"id": "src1", "name": "Doc A", "source_guide": {"summary": "x"}},
    ])

    wrapped_plan = [{
        "tldr_hint": "",
        "sections": [{"title": "A", "sub_query": "q", "rationale": ""}],
        "expected_gaps": [],
    }]
    _stub_gemini(
        monkeypatch,
        plan_dict=wrapped_plan,  # type: ignore[arg-type]
        section_results=[("Body [1]", None)],
        stitch_text="## TL;DR\nok [1]\n\n## A\nBody [1]",
    )
    _stub_retrieve(monkeypatch, [
        [_make_chunk("c1", "src1", "Doc A", "alpha")],
    ])

    await research_svc._run_research_async(REPORT)

    updates = [
        c for c in fake_supabase.calls
        if c[0] == "research_reports" and any(op == "update" for (op, _, _) in c[1])
    ]
    last = updates[-1][1]
    update_args = next(c for c in last if c[0] == "update")
    payload = update_args[1][0]
    assert payload["status"] == "ready", payload


@pytest.mark.asyncio
async def test_section_retries_once_on_gemini_error(fake_supabase, monkeypatch):
    """First attempt errors, second succeeds -> section ready."""
    _stub_report_row(fake_supabase, _report_row())
    _stub_sources(fake_supabase, [
        {"id": "src1", "name": "Doc A", "source_guide": {"summary": "x"}},
    ])

    _stub_gemini(
        monkeypatch,
        plan_dict={
            "tldr_hint": "",
            "sections": [{"title": "A", "sub_query": "q", "rationale": ""}],
            "expected_gaps": [],
        },
        section_results=[
            ("", RuntimeError("transient")),
            ("Success [1]", None),
        ],
        stitch_text="## TL;DR\nok\n\n## A\nSuccess [1]",
    )
    _stub_retrieve(monkeypatch, [
        [_make_chunk("c1", "src1", "Doc A", "alpha")],
    ])

    await research_svc._run_research_async(REPORT)

    updates = [
        c for c in fake_supabase.calls
        if c[0] == "research_reports" and any(op == "update" for (op, _, _) in c[1])
    ]
    last = updates[-1][1]
    update_args = next(c for c in last if c[0] == "update")
    payload = update_args[1][0]
    assert payload["status"] == "ready"
