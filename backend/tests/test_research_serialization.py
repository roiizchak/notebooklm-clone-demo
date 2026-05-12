"""Regression: research_reports insert/update payloads must be JSON-clean.

Phase 3.a extends B-COR-07 (UUID-in-body discipline) to the research pipeline.
Every Supabase write site in app.services.research must cast UUID -> str before
the body dict reaches the supabase-py client.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from app.services import research as research_svc
from app.services.gemini import ChatResult, EmbedResult, Usage
from app.services.rag import RetrievedChunk


REPORT = "44444444-4444-4444-4444-444444444441"


def _assert_no_raw_uuid_in_value(value: Any, path: str = "") -> None:
    assert not isinstance(value, UUID), (
        f"raw UUID found at {path or '<root>'}: {value!r}"
    )
    if isinstance(value, dict):
        for k, v in value.items():
            _assert_no_raw_uuid_in_value(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _assert_no_raw_uuid_in_value(v, f"{path}[{i}]")


def _assert_calls_clean(fake_supabase) -> None:
    write_ops = ("insert", "upsert", "update")
    for table, chain in fake_supabase.calls:
        for op, args, kwargs in chain:
            if op not in write_ops:
                continue
            for arg in args:
                if isinstance(arg, (dict, list)):
                    _assert_no_raw_uuid_in_value(arg, f"{table}.{op}.args")
                    try:
                        json.dumps(arg)
                    except TypeError as e:
                        raise AssertionError(
                            f"non-JSON-serialisable in {table}.{op}: {arg!r} ({e})"
                        ) from None


def test_enqueue_research_job_payload_has_no_raw_uuid(fake_supabase) -> None:
    """enqueue path: notebook_id / user_id / session_id passed as strings."""
    nb = str(uuid4())
    user = str(uuid4())
    fake_supabase.responses["research_reports"] = MagicMock(
        data=[{"id": REPORT, "status": "pending"}]
    )

    research_svc.enqueue_research_job(
        notebook_id=nb,
        user_id=user,
        session_id=None,
        question="Q",
        source_ids=[str(uuid4())],
    )
    _assert_calls_clean(fake_supabase)


def test_run_research_async_updates_have_no_raw_uuid(fake_supabase, monkeypatch) -> None:
    """Full happy path: every _mark / status update payload is JSON-clean."""
    nb = str(uuid4())
    user = str(uuid4())
    fake_supabase.responses["research_reports"] = MagicMock(
        data=[{
            "id": REPORT,
            "notebook_id": nb,
            "user_id": user,
            "session_id": None,
            "question": "Q",
            "source_ids": [],
            "status": "pending",
        }]
    )
    fake_supabase.responses["sources"] = MagicMock(data=[
        {"id": "src1", "name": "Doc A", "source_guide": {"summary": "x"}},
    ])

    fake = MagicMock()
    fake.embed_query = lambda text: EmbedResult(
        vectors=[[0.1] * 1536],
        usage=Usage(input_tokens=1, output_tokens=0, model_used="e", cost_usd=0.0),
    )
    fake.generate_research_plan = lambda **kw: (
        {
            "tldr_hint": "",
            "sections": [{"title": "A", "sub_query": "q", "rationale": ""}],
            "expected_gaps": [],
        },
        ChatResult(
            content="{}",
            usage=Usage(input_tokens=10, output_tokens=5, model_used="p", cost_usd=0.0),
        ),
    )
    fake.generate_research_section = lambda **kw: ChatResult(
        content="Body [1]",
        usage=Usage(input_tokens=10, output_tokens=5, model_used="s", cost_usd=0.0),
    )
    fake.generate_research_stitch = lambda **kw: ChatResult(
        content="## TL;DR\nok [1]",
        usage=Usage(input_tokens=10, output_tokens=5, model_used="st", cost_usd=0.0),
    )
    monkeypatch.setattr(research_svc, "get_gemini", lambda: fake)

    async def _ret(**kw):
        return [
            RetrievedChunk(
                chunk_id="c1",
                source_id="src1",
                source_name="Doc A",
                content="alpha beta",
                metadata={},
                similarity=0.9,
            )
        ]

    monkeypatch.setattr(research_svc, "retrieve", _ret)

    asyncio.run(research_svc._run_research_async(REPORT))
    _assert_calls_clean(fake_supabase)
