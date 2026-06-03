# tests/llm/test_gemini.py

"""Unit tests for :mod:`src.llm.gemini`.

A fake LangChain chat model is injected via ``client=``, so the tests never hit the
network nor require ``langchain_google_genai``. They cover ordered streaming, empty/
list-content flattening, the image data-URI, context/question inclusion and the
mode-specific (Claude-shared) system prompt. Arrange -> Act -> Assert throughout.
"""

from typing import Any, List, Tuple

import pytest

from src.llm.claude import ClaudeClient
from src.llm.gemini import GeminiClient
from src.models.enums import Mode


class _Chunk:
    """Minimal stand-in for a LangChain message chunk (exposes ``content``)."""

    def __init__(self, content: Any) -> None:
        """Stores the chunk content."""
        self.content = content


class _FakeChatModel:
    """Fake LangChain chat model; records the messages passed to ``stream``."""

    def __init__(self, chunks: List[Any]) -> None:
        """Stores canned chunk contents and a slot for the last messages."""
        self._chunks = chunks
        self.last_messages: Any = None

    def stream(self, messages: Any) -> Any:
        """Records messages and replays the canned chunks."""
        self.last_messages = messages
        return iter(_Chunk(content) for content in self._chunks)


def _make(chunks: List[Any]) -> Tuple[GeminiClient, _FakeChatModel]:
    """Builds a GeminiClient wired to a fake chat model replaying ``chunks``."""
    fake = _FakeChatModel(chunks)
    return GeminiClient(model="gemini-test", client=fake), fake


def test_stream_answer_yields_text_chunks_in_order() -> None:
    """stream_answer yields the fake text deltas in order."""
    client, _ = _make(["At", "tention", " is", " all"])
    assert list(client.stream_answer("Q")) == ["At", "tention", " is", " all"]


def test_stream_answer_skips_empty_and_flattens_list_content() -> None:
    """Empty strings are skipped and list content is flattened to its text parts."""
    client, _ = _make(["a", "", ["b", {"type": "text", "text": "c"}, {"type": "image_url"}]])
    assert list(client.stream_answer("Q")) == ["a", "b", "c"]


def test_model_client_builds_chatgoogle(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_model_client`` constructs a ``ChatGoogleGenerativeAI`` with model and key."""
    import sys
    import types

    captured: dict = {}

    class _FakeChatGoogle:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    fake_mod = types.ModuleType("langchain_google_genai")
    fake_mod.ChatGoogleGenerativeAI = _FakeChatGoogle  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_google_genai", fake_mod)

    built = GeminiClient(api_key="g_test", model="gem-x")._model_client()

    assert isinstance(built, _FakeChatGoogle)
    assert captured["model"] == "gem-x"
    assert captured["google_api_key"] == "g_test"


def test_image_is_attached_as_png_data_uri() -> None:
    """A screenshot is attached as a base64 PNG data URI image part."""
    client, fake = _make(["x"])
    list(client.stream_answer("Q", image_b64="QkFTRTY0"))
    parts = fake.last_messages[-1].content
    image_parts = [p for p in parts if isinstance(p, dict) and p.get("type") == "image_url"]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"] == "data:image/png;base64,QkFTRTY0"


def test_no_image_part_without_screenshot() -> None:
    """No image part is added when no screenshot is supplied."""
    client, fake = _make(["x"])
    list(client.stream_answer("Q"))
    parts = fake.last_messages[-1].content
    assert all(not (isinstance(p, dict) and p.get("type") == "image_url") for p in parts)


def test_question_and_context_are_included() -> None:
    """The question and rolling context appear in the user message text parts."""
    client, fake = _make(["x"])
    list(client.stream_answer("что такое GIL", context="говорили про потоки"))
    texts = [p["text"] for p in fake.last_messages[-1].content if p.get("type") == "text"]
    assert any("что такое GIL" in t for t in texts)
    assert any("говорили про потоки" in t for t in texts)


def test_system_prompt_is_mode_specific_and_matches_claude() -> None:
    """The system message uses the same mode-specific prompt as the Claude client."""
    client, fake = _make(["x"])
    list(client.stream_answer("Q", mode=Mode.ANSWER))
    assert fake.last_messages[0].content == ClaudeClient.build_system_prompt(Mode.ANSWER)


def test_set_model_resets_cached_client() -> None:
    """set_model updates the model and drops the cached chat model (forces a rebuild)."""
    client, _ = _make(["x"])
    client.set_model("new-model")
    assert client.model == "new-model"
    assert client._client is None


def test_missing_dependency_raises_runtime_error() -> None:
    """Without an injected client and no langchain_google_genai, a clear error is raised."""
    from unittest.mock import patch

    engine = GeminiClient(model="gemini-test")
    with patch.dict("sys.modules", {"langchain_google_genai": None}):
        with pytest.raises(RuntimeError, match="langchain-google-genai"):
            list(engine.stream_answer("Q"))
