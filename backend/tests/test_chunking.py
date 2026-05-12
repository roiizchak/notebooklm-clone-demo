"""Unit tests for the chunker."""

from app.services.ingestion import (
    CHARS_PER_TOKEN,
    CHUNK_TARGET_TOKENS,
    TextBlock,
    chunk_blocks,
    estimate_tokens,
)


def test_estimate_tokens_basic() -> None:
    assert estimate_tokens("a" * (CHARS_PER_TOKEN * 10)) == 10
    assert estimate_tokens("") == 1  # min 1


def test_chunker_short_text_single_chunk() -> None:
    blocks = [TextBlock(content="Hello world. This is short.", metadata={"page": 1})]
    chunks = chunk_blocks(blocks)
    assert len(chunks) == 1
    assert chunks[0].metadata == {"page": 1}
    assert chunks[0].chunk_index == 0


def test_chunker_splits_when_exceeding_target() -> None:
    # Build sentences whose total tokens far exceed the target.
    sentence = "This is one moderately long sentence used for testing the chunker. " * 20
    text = ". ".join([sentence] * 5)
    blocks = [TextBlock(content=text, metadata={"page": 7})]
    chunks = chunk_blocks(blocks)
    assert len(chunks) >= 2
    # Each non-final chunk should not greatly exceed target + a single sentence.
    for c in chunks[:-1]:
        assert c.token_count <= CHUNK_TARGET_TOKENS * 1.5
    # All chunks share the source page metadata.
    assert all(c.metadata.get("page") == 7 for c in chunks)


def test_chunker_preserves_metadata_per_block() -> None:
    blocks = [
        TextBlock(content="A. B. C.", metadata={"page": 1}),
        TextBlock(content="X. Y. Z.", metadata={"page": 2}),
    ]
    chunks = chunk_blocks(blocks)
    pages = {c.metadata["page"] for c in chunks}
    assert pages == {1, 2}


def test_chunker_skips_empty_blocks() -> None:
    blocks = [
        TextBlock(content="", metadata={"page": 1}),
        TextBlock(content="Real content here.", metadata={"page": 2}),
    ]
    chunks = chunk_blocks(blocks)
    assert len(chunks) == 1
    assert chunks[0].metadata == {"page": 2}
