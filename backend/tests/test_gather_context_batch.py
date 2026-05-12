"""P-PRF-01: _gather_context issues one query for source_chunks regardless of source count."""

from unittest.mock import MagicMock


def test_gather_context_batches_chunk_queries(fake_supabase, auth_user_id) -> None:
    sources = [
        {"id": f"22222222-2222-2222-2222-22222222222{i}", "name": f"S{i}", "status": "ready"}
        for i in range(5)
    ]
    fake_supabase.responses["sources"] = MagicMock(data=sources)

    chunks: list[dict] = []
    for i in range(5):
        chunks.append({
            "source_id": f"22222222-2222-2222-2222-22222222222{i}",
            "content": f"text {i}",
            "chunk_index": 0,
        })
    fake_supabase.responses["source_chunks"] = MagicMock(data=chunks)

    from app.services.audio import _gather_context

    ctx = _gather_context(notebook_id="11111111-1111-1111-1111-111111111111")
    assert "text 0" in ctx.text
    assert "text 4" in ctx.text
    assert len(ctx.source_ids) == 5

    chunk_calls = [c for c in fake_supabase.calls if c[0] == "source_chunks"]
    assert len(chunk_calls) == 1, f"expected 1 batched query, got {len(chunk_calls)}"

    chain_ops = [m for (m, _, _) in chunk_calls[0][1]]
    assert "in_" in chain_ops, f"expected .in_ in chain, got {chain_ops}"
