"""Unit tests for cost calculation + model whitelisting."""

from app.services import gemini


def test_calculate_cost_chat_3_flash_preview() -> None:
    # Pricing: input $0.50/1M, output $3.00/1M
    cost = gemini.calculate_cost("gemini-3-flash-preview", 1_000_000, 1_000_000)
    assert abs(cost - 3.50) < 1e-6


def test_calculate_cost_embedding() -> None:
    cost = gemini.calculate_cost("gemini-embedding-2", 1_000_000, 0)
    assert abs(cost - 0.20) < 1e-6


def test_calculate_cost_unknown_model_returns_zero() -> None:
    assert gemini.calculate_cost("unknown-model", 1_000_000, 1_000_000) == 0.0


def test_chat_model_whitelist() -> None:
    assert gemini.is_chat_model_allowed("gemini-3-flash-preview")
    assert gemini.is_chat_model_allowed("gemini-3.1-flash-lite")
    assert not gemini.is_chat_model_allowed("gemini-2.5-pro")
    assert not gemini.is_chat_model_allowed("anything-else")
