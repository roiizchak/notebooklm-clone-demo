"""T-TST-02 service: generate_audio_overview wires Gemini + storage + status updates."""

from unittest.mock import MagicMock


AUDIO = "33333333-3333-3333-3333-333333333331"
NB = "11111111-1111-1111-1111-111111111111"


def _audio_row(user_id: str, *, status: str = "pending") -> dict:
    return {
        "id": AUDIO,
        "notebook_id": NB,
        "user_id": user_id,
        "target_minutes": 5,
        "status": status,
        "custom_instructions": None,
    }


def _ttsresult(wav_bytes: bytes, *, duration: float = 12.5, cost: float = 0.30):
    from app.services.gemini import TtsResult, Usage

    return TtsResult(
        wav_bytes=wav_bytes,
        duration_seconds=duration,
        usage=Usage(
            input_tokens=100,
            output_tokens=int(duration * 25),
            model_used="gemini-3.1-flash-tts-preview",
            cost_usd=cost,
        ),
    )


def _chatresult(text: str, *, cost: float = 0.05):
    from app.services.gemini import ChatResult, Usage

    return ChatResult(
        content=text,
        usage=Usage(
            input_tokens=200,
            output_tokens=400,
            model_used="gemini-3-flash-preview",
            cost_usd=cost,
        ),
    )


class _FakeGemini:
    def __init__(self) -> None:
        self.transcript_calls = 0
        self.tts_calls = 0

    def generate_transcript(self, *, context, target_minutes, custom_instructions, speakers):
        self.transcript_calls += 1
        assert context  # context was gathered
        assert target_minutes == 5
        return _chatresult("Alice: Hi.\nBob: Hello.")

    def synthesize_dialogue(self, *, script, speakers):
        self.tts_calls += 1
        assert script.startswith("Alice:")
        return _ttsresult(b"WAVDATA" * 1000)


def test_generate_audio_overview_uploads_wav_and_marks_ready(
    fake_supabase, auth_user_id, monkeypatch
) -> None:
    """Happy path: row read -> generating -> transcript -> tts -> upload -> ready."""
    state = {"audio_calls": 0, "uploaded": []}

    def _audio_resp(chain):
        state["audio_calls"] += 1
        ops = [c[0] for c in chain]
        if "select" in ops:
            # _generate_audio_async first SELECTs the row to load it.
            return [_audio_row(auth_user_id)]
        # update -> data echo (return shape isn't read).
        return [{"id": AUDIO}]

    fake_supabase.responses["audio_overviews"] = _audio_resp
    fake_supabase.responses["sources"] = MagicMock(
        data=[{"id": "s1", "status": "ready", "name": "S"}]
    )
    fake_supabase.responses["source_chunks"] = MagicMock(
        data=[{"source_id": "s1", "content": "ctx body", "chunk_index": 0}]
    )

    # Storage upload: capture the bytes + path; storage is patched at the
    # audio service's import site (upload_bytes from app.services.storage).
    import app.services.audio as audio_svc

    def _upload_capture(bucket, path, data, content_type):
        state["uploaded"].append({
            "bucket": bucket,
            "path": path,
            "len": len(data),
            "content_type": content_type,
        })

    monkeypatch.setattr(audio_svc, "upload_bytes", _upload_capture)

    fake = _FakeGemini()
    monkeypatch.setattr(audio_svc, "get_gemini", lambda: fake)

    # log_usage may try to insert usage rows; make it a noop so we don't
    # have to thread through an extra fake_supabase response.
    monkeypatch.setattr(audio_svc, "log_usage", lambda **kw: None)

    audio_svc.run_audio_generation_blocking(AUDIO)

    # Gemini was called exactly once for each phase.
    assert fake.transcript_calls == 1
    assert fake.tts_calls == 1

    # Storage upload happened with the audio bucket + canonical path.
    assert len(state["uploaded"]) == 1
    up = state["uploaded"][0]
    assert up["bucket"] == "audio"
    assert up["path"] == f"{auth_user_id}/{NB}/{AUDIO}.wav"
    assert up["content_type"] == "audio/wav"
    assert up["len"] > 0

    # At least one update to audio_overviews happened (status transitions).
    update_calls = [
        c for c in fake_supabase.calls
        if c[0] == "audio_overviews" and any(op == "update" for (op, _, _) in c[1])
    ]
    assert update_calls, "expected at least one update to audio_overviews"

    # The final update fields should mark status=ready and persist the path.
    final_updates: list[dict] = []
    for _, chain in update_calls:
        for op, args, _kw in chain:
            if op == "update" and args:
                final_updates.append(args[0])
    statuses = [f.get("status") for f in final_updates if "status" in f]
    assert "generating" in statuses
    assert "ready" in statuses
    ready_update = next(f for f in final_updates if f.get("status") == "ready")
    assert ready_update["audio_path"] == f"{auth_user_id}/{NB}/{AUDIO}.wav"
    assert ready_update["script"].startswith("Alice:")
    # cost_usd is sum of transcript + tts cost in our fakes (0.05 + 0.30).
    assert abs(ready_update["cost_usd"] - 0.35) < 1e-9


def test_generate_audio_overview_marks_failed_when_no_sources(
    fake_supabase, auth_user_id, monkeypatch
) -> None:
    """Notebook with zero ready sources -> status=failed with error message."""
    state = {"audio_calls": 0}

    def _audio_resp(chain):
        state["audio_calls"] += 1
        ops = [c[0] for c in chain]
        if "select" in ops:
            return [_audio_row(auth_user_id)]
        return [{"id": AUDIO}]

    fake_supabase.responses["audio_overviews"] = _audio_resp
    fake_supabase.responses["sources"] = MagicMock(data=[])  # nothing ready
    fake_supabase.responses["source_chunks"] = MagicMock(data=[])

    import app.services.audio as audio_svc

    # If Gemini gets called, the test catches that as a failure of the
    # short-circuit logic.
    class _ShouldNotCall:
        def generate_transcript(self, **_kw):
            raise AssertionError("transcript should not be called when context empty")

        def synthesize_dialogue(self, **_kw):
            raise AssertionError("synth should not be called when context empty")

    monkeypatch.setattr(audio_svc, "get_gemini", lambda: _ShouldNotCall())
    monkeypatch.setattr(audio_svc, "upload_bytes", lambda *a, **k: None)
    monkeypatch.setattr(audio_svc, "log_usage", lambda **kw: None)

    audio_svc.run_audio_generation_blocking(AUDIO)

    update_calls = [
        c for c in fake_supabase.calls
        if c[0] == "audio_overviews" and any(op == "update" for (op, _, _) in c[1])
    ]
    final_updates: list[dict] = []
    for _, chain in update_calls:
        for op, args, _kw in chain:
            if op == "update" and args:
                final_updates.append(args[0])
    statuses = [f.get("status") for f in final_updates if "status" in f]
    assert "failed" in statuses
    failed = next(f for f in final_updates if f.get("status") == "failed")
    assert "no ready sources" in (failed.get("error") or "").lower()


def test_generate_audio_overview_marks_failed_when_tts_raises(
    fake_supabase, auth_user_id, monkeypatch
) -> None:
    """Gemini TTS exception is caught and surfaced as status=failed."""
    state = {"audio_calls": 0}

    def _audio_resp(chain):
        state["audio_calls"] += 1
        ops = [c[0] for c in chain]
        if "select" in ops:
            return [_audio_row(auth_user_id)]
        return [{"id": AUDIO}]

    fake_supabase.responses["audio_overviews"] = _audio_resp
    fake_supabase.responses["sources"] = MagicMock(
        data=[{"id": "s1", "status": "ready", "name": "S"}]
    )
    fake_supabase.responses["source_chunks"] = MagicMock(
        data=[{"source_id": "s1", "content": "body", "chunk_index": 0}]
    )

    import app.services.audio as audio_svc

    class _BadTtsGemini:
        def generate_transcript(self, **_kw):
            return _chatresult("Alice: Hi.\nBob: Hello.")

        def synthesize_dialogue(self, **_kw):
            raise RuntimeError("gemini tts blew up")

    monkeypatch.setattr(audio_svc, "get_gemini", lambda: _BadTtsGemini())
    monkeypatch.setattr(audio_svc, "upload_bytes", lambda *a, **k: None)
    monkeypatch.setattr(audio_svc, "log_usage", lambda **kw: None)

    audio_svc.run_audio_generation_blocking(AUDIO)

    update_calls = [
        c for c in fake_supabase.calls
        if c[0] == "audio_overviews" and any(op == "update" for (op, _, _) in c[1])
    ]
    final_updates: list[dict] = []
    for _, chain in update_calls:
        for op, args, _kw in chain:
            if op == "update" and args:
                final_updates.append(args[0])
    statuses = [f.get("status") for f in final_updates if "status" in f]
    assert "failed" in statuses
    failed = next(f for f in final_updates if f.get("status") == "failed")
    assert "gemini tts blew up" in (failed.get("error") or "")
