"""T-TST-08 gotcha pin: gemini-3.1-pro-preview must remain in _PRICING and CHAT_ALLOWED.

Future "optimize" passes can't silently regress the Phase 3.a Pro stitch step.
Verified pricing source: https://ai.google.dev/gemini-api/docs/pricing (May 2026 fetch).
"""

from app.services.gemini import (
    CHAT_ALLOWED,
    RESEARCH_STITCH_MODEL,
    _PRICING,
    calculate_cost,
)


def test_pro_model_id_consistent() -> None:
    assert RESEARCH_STITCH_MODEL == "gemini-3.1-pro-preview"


def test_pro_model_in_chat_allowed() -> None:
    assert RESEARCH_STITCH_MODEL in CHAT_ALLOWED


def test_pro_model_in_pricing_table() -> None:
    entry = _PRICING.get(RESEARCH_STITCH_MODEL)
    assert entry is not None
    assert isinstance(entry["input"], float)
    assert isinstance(entry["output"], float)
    assert entry["input"] > 0
    assert entry["output"] > 0


def test_pro_pricing_matches_verified_may_2026_rate() -> None:
    """If Google changes Pro pricing, update both this test and CLAUDE.md.

    Standard tier, prompts <=200k tokens (May 2026 verified):
      input  $2.00 / 1M
      output $12.00 / 1M
    """
    entry = _PRICING[RESEARCH_STITCH_MODEL]
    assert entry["input"] == 2.00
    assert entry["output"] == 12.00


def test_calculate_cost_uses_pro_rate() -> None:
    """Sanity: a 10k in / 3k out stitch costs ~$0.056."""
    cost = calculate_cost(RESEARCH_STITCH_MODEL, 10_000, 3_000)
    # 10k/1M * 2.00 + 3k/1M * 12.00 = 0.02 + 0.036 = 0.056
    assert round(cost, 4) == 0.0560
