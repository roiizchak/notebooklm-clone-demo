"""T-TST-07: ingestion.extract_youtube uses YouTubeTranscriptApi().fetch().snippets.

youtube-transcript-api 1.x removed the legacy static `get_transcript`.
Code now instantiates the class, calls `.fetch(video_id)`, and iterates the
`.snippets` attribute (each `FetchedTranscriptSnippet(text, start, duration)`).
See CLAUDE.md note 2. This test pins that exact contract.
"""

import sys
import types
from unittest.mock import MagicMock


def test_extract_youtube_iterates_snippets(monkeypatch) -> None:
    from app.services import ingestion as ing_mod

    fake_snippets = [
        MagicMock(text="hello world", start=0.0, duration=1.5),
        MagicMock(text="second line", start=1.5, duration=2.0),
        MagicMock(text="third bit", start=3.5, duration=30.0),
    ]
    fake_transcript = MagicMock(snippets=fake_snippets)
    fake_api_instance = MagicMock()
    fake_api_instance.fetch.return_value = fake_transcript
    FakeApiClass = MagicMock(return_value=fake_api_instance)

    # extract_youtube imports `from youtube_transcript_api import YouTubeTranscriptApi`
    # *inside* the function — we must patch the symbol at the module sys.modules
    # level (and the errors submodule it also imports).
    fake_mod = types.ModuleType("youtube_transcript_api")
    fake_mod.YouTubeTranscriptApi = FakeApiClass
    fake_errors = types.ModuleType("youtube_transcript_api._errors")
    fake_errors.NoTranscriptFound = type("NoTranscriptFound", (Exception,), {})
    fake_errors.TranscriptsDisabled = type("TranscriptsDisabled", (Exception,), {})
    fake_errors.VideoUnavailable = type("VideoUnavailable", (Exception,), {})

    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake_mod)
    monkeypatch.setitem(sys.modules, "youtube_transcript_api._errors", fake_errors)

    blocks = ing_mod.extract_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    # The fetch call was made with the 11-char video id parsed from the URL.
    fake_api_instance.fetch.assert_called_once_with("dQw4w9WgXcQ")

    # Snippet text must surface in the extracted blocks.
    joined = " ".join(b.content for b in blocks)
    assert "hello world" in joined
    assert "second line" in joined
    assert "third bit" in joined
