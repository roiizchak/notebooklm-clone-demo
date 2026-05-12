"""Unit tests for Phase 3.a knowledge-only Google-Search grounding helpers.

Covers:
- ``_extract_grounding`` (gemini.py) shape parser tolerates missing fields.
- ``_inject_grounding_citations`` (research.py) splices ``[n]`` tokens at
  byte offsets in reverse end-index order, dedupes by URI, attaches the
  ``metadata.type == 'web'`` + ``url`` payload the frontend expects.
- Graceful degradation when grounding is empty.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.gemini import (
    GroundingHit,
    GroundingSupport,
    _extract_grounding,
)
from app.services.research import (
    _domain_of,
    _inject_grounding_citations,
    _stable_web_chunk_id,
)


# ---------- _extract_grounding ----------


def _fake_response(chunks: list[dict] | None, supports: list[dict] | None):
    """Build a SimpleNamespace mimicking the Gemini response shape used by
    ``response.candidates[0].grounding_metadata`` accessors."""

    def _ns(d):
        return SimpleNamespace(**d)

    grounding = SimpleNamespace(
        grounding_chunks=[_ns(c) for c in (chunks or [])],
        grounding_supports=[_ns(s) for s in (supports or [])],
    )
    candidate = SimpleNamespace(grounding_metadata=grounding)
    return SimpleNamespace(candidates=[candidate])


def test_extract_grounding_parses_chunks_and_supports():
    resp = _fake_response(
        chunks=[
            {"web": SimpleNamespace(uri="https://a.com/x", title="A page")},
            {"web": SimpleNamespace(uri="https://b.org/y", title="B page")},
        ],
        supports=[
            {
                "segment": SimpleNamespace(start_index=0, end_index=10, text="claim one"),
                "grounding_chunk_indices": [0],
                "confidence_scores": [0.9],
            },
            {
                "segment": SimpleNamespace(start_index=11, end_index=30, text="claim two"),
                "grounding_chunk_indices": [0, 1],
                "confidence_scores": [0.7, 0.8],
            },
        ],
    )
    hits, supports = _extract_grounding(resp)
    assert [h.uri for h in hits] == ["https://a.com/x", "https://b.org/y"]
    assert [h.title for h in hits] == ["A page", "B page"]
    assert [s.end_index for s in supports] == [10, 30]
    assert supports[1].hit_indices == [0, 1]
    assert supports[1].confidence == 0.8  # max(scores)


def test_extract_grounding_absent_returns_empty():
    """No candidates / no grounding_metadata -> empty lists, no exception."""
    assert _extract_grounding(SimpleNamespace(candidates=[])) == ([], [])
    cand = SimpleNamespace(grounding_metadata=None)
    resp = SimpleNamespace(candidates=[cand])
    assert _extract_grounding(resp) == ([], [])


def test_extract_grounding_chunk_without_web_keeps_index_alignment():
    """A grounding chunk missing the .web field becomes an empty-URI placeholder
    so support hit_indices stay aligned with the hits list."""
    resp = _fake_response(
        chunks=[
            {"web": None},
            {"web": SimpleNamespace(uri="https://a.com/x", title="A")},
        ],
        supports=[],
    )
    hits, _ = _extract_grounding(resp)
    assert len(hits) == 2
    assert hits[0].uri == ""
    assert hits[1].uri == "https://a.com/x"


# ---------- helpers ----------


def test_stable_web_chunk_id_deterministic():
    a = _stable_web_chunk_id("https://example.com/page")
    b = _stable_web_chunk_id("https://example.com/page")
    c = _stable_web_chunk_id("https://example.com/other")
    assert a == b
    assert a != c
    assert a.startswith("web:")


def test_domain_of_extracts_netloc():
    assert _domain_of("https://www.example.com/a/b?c=1") == "www.example.com"
    assert _domain_of("not a url") == "not a url"


# ---------- _inject_grounding_citations ----------


def test_inject_grounding_inserts_tokens_at_byte_offsets():
    """One support pointing at one hit -> single [1] token spliced after end_index."""
    text = "The capital of France is Paris."
    # end_index points right after "Paris" (byte offset 30).
    hits = [GroundingHit(uri="https://geo.example.com/fr", title="France geo")]
    supports = [
        GroundingSupport(
            end_index=30,
            text_segment="The capital of France is Paris",
            hit_indices=[0],
            confidence=0.95,
        )
    ]
    new_text, citations = _inject_grounding_citations(text, hits, supports)
    assert new_text == "The capital of France is Paris[1]."
    assert len(citations) == 1
    c = citations[0]
    assert c.number == 1
    assert c.source_name == "France geo"
    assert c.metadata == {
        "type": "web",
        "url": "https://geo.example.com/fr",
        "domain": "geo.example.com",
    }
    assert c.similarity == 0.95
    assert c.chunk_id == c.source_id == _stable_web_chunk_id("https://geo.example.com/fr")


def test_inject_grounding_reverse_order_keeps_offsets_correct():
    """Two supports -> inserting the later end_index first leaves earlier offset valid.

    ``end_index`` points right after the cited span (exclusive). With
    ``"First fact"`` ending at byte 10 and ``"Second fact extra"`` ending at
    byte 29 (just before the final period), tokens land cleanly before
    punctuation.
    """
    text = "First fact. Second fact extra."
    hits = [
        GroundingHit(uri="https://one.com", title="One"),
        GroundingHit(uri="https://two.com", title="Two"),
    ]
    supports = [
        GroundingSupport(end_index=10, text_segment="First fact", hit_indices=[0]),
        GroundingSupport(end_index=29, text_segment="Second fact extra", hit_indices=[1]),
    ]
    new_text, citations = _inject_grounding_citations(text, hits, supports)
    assert new_text == "First fact[1]. Second fact extra[2]."
    assert [c.number for c in citations] == [1, 2]


def test_inject_grounding_dedupes_repeated_uri():
    """The same URI cited twice yields one SectionCitation with the same number."""
    text = "Claim A. Claim B."
    hits = [GroundingHit(uri="https://x.com", title="X")]
    supports = [
        GroundingSupport(end_index=7, text_segment="Claim A", hit_indices=[0]),
        GroundingSupport(end_index=16, text_segment="Claim B", hit_indices=[0]),
    ]
    new_text, citations = _inject_grounding_citations(text, hits, supports)
    assert len(citations) == 1
    assert citations[0].number == 1
    assert new_text == "Claim A[1]. Claim B[1]."


def test_inject_grounding_multiple_hits_per_support():
    """One support with two distinct hits -> appends [1][2] in order."""
    text = "Combined claim."
    hits = [
        GroundingHit(uri="https://a.com", title="A"),
        GroundingHit(uri="https://b.com", title="B"),
    ]
    supports = [
        GroundingSupport(end_index=14, text_segment="Combined claim", hit_indices=[0, 1]),
    ]
    new_text, citations = _inject_grounding_citations(text, hits, supports)
    assert new_text == "Combined claim[1][2]."
    assert [c.number for c in citations] == [1, 2]


def test_inject_grounding_empty_inputs_returns_text_unchanged():
    """No grounding metadata -> degrade gracefully (return input, empty citations)."""
    text = "Plain text."
    assert _inject_grounding_citations(text, [], []) == (text, [])
    assert _inject_grounding_citations(text, [GroundingHit(uri="x", title="t")], []) == (
        text,
        [],
    )
    assert _inject_grounding_citations(
        text,
        [],
        [GroundingSupport(end_index=5, text_segment="Plain", hit_indices=[])],
    ) == (text, [])


def test_inject_grounding_hit_without_uri_skipped():
    """A placeholder hit (web=None upstream -> uri='') gets ignored, not numbered."""
    text = "X is Y."
    hits = [GroundingHit(uri="", title=""), GroundingHit(uri="https://real.com", title="Real")]
    supports = [
        GroundingSupport(end_index=6, text_segment="X is Y", hit_indices=[0, 1]),
    ]
    new_text, citations = _inject_grounding_citations(text, hits, supports)
    # Only the real URI shows up.
    assert len(citations) == 1
    assert citations[0].source_name == "Real"
    # Token reflects the single valid citation.
    assert new_text == "X is Y[1]."


def test_inject_grounding_out_of_range_index_ignored():
    """Support pointing at a non-existent hit index is silently dropped, no crash."""
    text = "Hello world"
    hits = [GroundingHit(uri="https://only.com", title="Only")]
    supports = [
        GroundingSupport(end_index=5, text_segment="Hello", hit_indices=[5]),
        GroundingSupport(end_index=11, text_segment="world", hit_indices=[0]),
    ]
    new_text, citations = _inject_grounding_citations(text, hits, supports)
    assert new_text == "Hello world[1]"
    assert len(citations) == 1
