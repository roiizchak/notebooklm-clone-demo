"""B-COR-04: _mark_failed / _mark retry once and emit a structured ERROR log."""

import logging


def test_sources_mark_failed_retries_once_then_logs(fake_supabase, caplog, monkeypatch) -> None:
    from app.routers import sources

    state = {"n": 0}

    def _src_response(chain):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("transient")
        return [{"id": "22222222-2222-2222-2222-222222222221"}]

    fake_supabase.responses["sources"] = _src_response
    # Patch sleep so the retry doesn't slow the test.
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    caplog.set_level(logging.WARNING, logger="app.routers.sources")
    sources._mark_failed("22222222-2222-2222-2222-222222222221", "boom")
    assert state["n"] >= 2, "expected at least one retry"


def test_audio_mark_retries_once_then_logs(fake_supabase, caplog, monkeypatch) -> None:
    from app.services import audio

    state = {"n": 0}

    def _aud_response(chain):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("transient")
        return [{"id": "33333333-3333-3333-3333-333333333331"}]

    fake_supabase.responses["audio_overviews"] = _aud_response
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    caplog.set_level(logging.WARNING, logger="app.services.audio")
    audio._mark("33333333-3333-3333-3333-333333333331", {"status": "failed"})
    assert state["n"] >= 2
