"""T-TST-08: GeminiService._embed calls embed_content once per input text.

CLAUDE.md note 1: google-genai's embed_content does not reliably return one
embedding per content when passed a list. The loop is deliberate. A future
"optimization" that batches the call into a single embed_content invocation
must FAIL this test.
"""

from unittest.mock import MagicMock


def test_embed_calls_embed_content_once_per_text() -> None:
    from app.services import gemini as gemini_mod

    inputs = ["alpha", "beta", "gamma", "delta"]
    call_count = {"n": 0}
    seen_contents: list = []

    def _fake_embed(*args, **kwargs):
        call_count["n"] += 1
        seen_contents.append(kwargs.get("contents"))
        resp = MagicMock()
        resp.embeddings = [MagicMock(values=[0.1] * 1536)]
        resp.total_billable_tokens = 3
        return resp

    svc = gemini_mod.get_gemini()
    svc._client = MagicMock()
    svc._client.models.embed_content.side_effect = _fake_embed

    result = svc._embed(inputs, task_type="RETRIEVAL_DOCUMENT")

    assert (
        call_count["n"] == len(inputs)
    ), f"expected {len(inputs)} embed_content calls, got {call_count['n']}"
    # Each call should have been passed a single string (not the whole list).
    assert seen_contents == inputs, f"expected one text per call; got {seen_contents}"
    # Result shape sanity.
    assert len(result.vectors) == len(inputs)
    assert all(len(v) == 1536 for v in result.vectors)
