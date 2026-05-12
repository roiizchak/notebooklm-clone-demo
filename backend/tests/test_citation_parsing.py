"""Unit tests for citation parsing in rag.py."""

from app.services.rag import RetrievedChunk, parse_citations


def _make_chunks(n: int) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=f"cid-{i}",
            source_id=f"sid-{i}",
            source_name=f"src-{i}",
            content=f"chunk {i} content text",
            metadata={"page": i},
            similarity=0.9 - (i * 0.01),
        )
        for i in range(1, n + 1)
    ]


def test_parse_in_range_citations() -> None:
    chunks = _make_chunks(3)
    text = "Foo [1] bar [2] baz."
    cits = parse_citations(text, chunks)
    assert [c.number for c in cits] == [1, 2]
    assert cits[0].source_id == "sid-1"
    assert cits[1].source_id == "sid-2"


def test_parse_out_of_range_dropped() -> None:
    chunks = _make_chunks(2)
    text = "Foo [1] bar [9] baz [0]."
    cits = parse_citations(text, chunks)
    assert [c.number for c in cits] == [1]


def test_parse_dedupes_same_citation_number() -> None:
    chunks = _make_chunks(3)
    text = "Foo [2]. Bar [2]. Baz [3]."
    cits = parse_citations(text, chunks)
    assert [c.number for c in cits] == [2, 3]


def test_parse_no_citations() -> None:
    chunks = _make_chunks(3)
    cits = parse_citations("plain text with no brackets", chunks)
    assert cits == []
