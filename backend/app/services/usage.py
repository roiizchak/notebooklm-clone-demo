"""Usage logging helper.

Inserts one row per Gemini operation (embedding, chat, summary) into
`usage_logs` for cost visibility. Failures are swallowed — a logging
write must never break a user-facing request.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.services.gemini import Usage
from app.services.supabase_client import get_supabase

log = logging.getLogger(__name__)


def count_operations_24h(user_id: str, operation_types: list[str]) -> int:
    """Count this user's usage_logs rows of the given operation types in the
    last 24h. Backs the per-user daily caps on paid Gemini endpoints (F1).

    Best-effort cost guardrail, NOT atomic: log_usage writes occur *after* the
    Gemini call, so concurrent bursts within one window can all pass the
    pre-check (TOCTOU). True atomic limiting would need Redis / advisory locks,
    which this Vercel-serverless architecture deliberately avoids.

    Uses the existing idx_usage_logs_user_id + idx_usage_logs_created_at indexes.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    res = (
        get_supabase()
        .table("usage_logs")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .in_("operation_type", operation_types)
        .gte("created_at", cutoff)
        .execute()
    )
    # supabase-py returns an int via res.count when count='exact'; fall back to
    # row length otherwise (and stay robust to test mocks where count is a Mock).
    count = getattr(res, "count", None)
    if isinstance(count, int):
        return count
    return len(getattr(res, "data", None) or [])


def _scrub_uuids(value: Any) -> Any:
    """Recursively convert UUID instances to str so the dict is JSON-serialisable
    by httpx. Defends against UUID FastAPI path params reaching the body."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _scrub_uuids(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_uuids(v) for v in value]
    return value


def log_usage(
    *,
    user_id: str,
    notebook_id: str | UUID | None,
    operation_type: str,
    usage: Usage,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not usage.model_used:
        return
    try:
        get_supabase().table("usage_logs").insert(
            {
                "user_id": str(user_id) if isinstance(user_id, UUID) else user_id,
                "notebook_id": str(notebook_id) if isinstance(notebook_id, UUID) else notebook_id,
                "operation_type": operation_type,
                "model_used": usage.model_used,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": round(usage.cost_usd, 6),
                "metadata": _scrub_uuids(metadata or {}),
            }
        ).execute()
    except Exception as e:  # noqa: BLE001
        log.warning("usage_log insert failed: %s", e)
