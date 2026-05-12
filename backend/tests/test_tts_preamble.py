"""T-TST-06: synthesize_dialogue MUST prepend the conversation preamble.

Without the "TTS the following conversation between X and Y:" framing,
gemini-3.1-flash-tts-preview narrates in a single voice even when
MultiSpeakerVoiceConfig is set. See CLAUDE.md note 12a.
"""

from unittest.mock import MagicMock


def test_synthesize_dialogue_prepends_conversation_preamble() -> None:
    from app.services import gemini as gemini_mod

    captured: dict = {}

    fake_response = MagicMock()
    fake_response.candidates = [
        MagicMock(
            content=MagicMock(
                parts=[MagicMock(inline_data=MagicMock(data=b"\x00" * 100))]
            )
        )
    ]
    fake_response.usage_metadata = MagicMock(
        prompt_token_count=10, candidates_token_count=0
    )

    def _fake_generate_content(*args, **kwargs):
        if "contents" in kwargs:
            captured["contents"] = kwargs["contents"]
        elif len(args) >= 2:
            captured["contents"] = args[1]
        return fake_response

    svc = gemini_mod.get_gemini()
    # _client is an instance attribute (set in __post_init__). Stub its models.
    svc._client = MagicMock()
    svc._client.models.generate_content.side_effect = _fake_generate_content

    speakers = [
        gemini_mod.SpeakerVoice(speaker="Alice", voice_name="Kore"),
        gemini_mod.SpeakerVoice(speaker="Bob", voice_name="Puck"),
    ]
    svc.synthesize_dialogue(
        script="Alice: Hi.\nBob: Hello.",
        speakers=speakers,
    )

    contents = captured.get("contents", "")
    text = contents if isinstance(contents, str) else str(contents)
    assert (
        "TTS the following conversation between" in text
    ), f"missing preamble; got: {text[:200]}"
    assert "Alice" in text and "Bob" in text
