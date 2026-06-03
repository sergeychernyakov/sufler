# tests/llm/test_groq.py

"""Unit tests for :mod:`src.llm.groq`.

A fake LangChain chat model is injected via ``client=``, so the tests never hit the
network nor require ``langchain_groq``. They cover ordered streaming, the OpenAI-style
image part, context/question inclusion and the mode-specific (Claude-shared) system
prompt. Arrange -> Act -> Assert throughout.
"""

from typing import Any, List, Tuple

import pytest

from src.llm.claude import ClaudeClient
from src.llm.groq import GroqClient
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


def _make(chunks: List[Any]) -> Tuple[GroqClient, _FakeChatModel]:
    """Builds a GroqClient wired to a fake chat model replaying ``chunks``."""
    fake = _FakeChatModel(chunks)
    return GroqClient(model="groq-test", client=fake), fake


def test_stream_answer_yields_text_chunks_in_order() -> None:
    """stream_answer yields the fake text deltas in order."""
    client, _ = _make(["po", "ng"])
    assert list(client.stream_answer("Q")) == ["po", "ng"]


def test_stream_answer_skips_empty_and_flattens_list_content() -> None:
    """Empty strings are skipped and list content is flattened to its text parts."""
    client, _ = _make(["a", "", ["b", {"type": "text", "text": "c"}, {"type": "image_url"}]])
    assert list(client.stream_answer("Q")) == ["a", "b", "c"]


def test_model_client_builds_chatgroq(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_model_client`` constructs a ``ChatGroq`` with the configured model and key."""
    import sys
    import types

    captured: dict = {}

    class _FakeChatGroq:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    fake_mod = types.ModuleType("langchain_groq")
    fake_mod.ChatGroq = _FakeChatGroq  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_groq", fake_mod)

    built = GroqClient(api_key="gsk_test", model="groq-x")._model_client()

    assert isinstance(built, _FakeChatGroq)
    assert captured["model"] == "groq-x"
    assert captured["api_key"] == "gsk_test"


def test_image_is_attached_as_openai_style_data_uri() -> None:
    """A screenshot is attached as an OpenAI-style image part (``image_url`` is a dict)."""
    client, fake = _make(["x"])
    list(client.stream_answer("Q", image_b64="QkFTRTY0"))
    parts = fake.last_messages[-1].content
    image_parts = [p for p in parts if isinstance(p, dict) and p.get("type") == "image_url"]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"] == {"url": "data:image/png;base64,QkFTRTY0"}


def test_question_and_context_are_included() -> None:
    """The question and rolling context appear in the user message text parts."""
    client, fake = _make(["x"])
    list(client.stream_answer("что такое mutex", context="говорили про потоки"))
    texts = [p["text"] for p in fake.last_messages[-1].content if p.get("type") == "text"]
    assert any("что такое mutex" in t for t in texts)
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
    """Without an injected client and no langchain_groq, a clear error is raised."""
    from unittest.mock import patch

    engine = GroqClient(model="groq-test")
    with patch.dict("sys.modules", {"langchain_groq": None}):
        with pytest.raises(RuntimeError, match="langchain-groq"):
            list(engine.stream_answer("Q"))
