# tests/llm/test_claude.py

"""Unit tests for :mod:`src.llm.claude`.

These tests never hit the network: a fake Anthropic client is injected whose
``messages.stream(...)`` returns a context manager exposing a ``text_stream``
iterator of canned chunks. They cover the mode-specific system prompt, the
multimodal content blocks (image/context inclusion), model pass-through, and
that streaming yields chunks in order.
"""

from types import TracebackType
from typing import Any, Dict, Iterator, List, Optional, Type

import pytest

from src.config import config
from src.llm.claude import ClaudeClient
from src.models.enums import Mode


class _FakeStream:
    """Fake streaming context manager mimicking ``MessageStream``."""

    def __init__(self, chunks: List[str]) -> None:
        """Stores the chunks to be replayed via ``text_stream``."""
        self.text_stream: Iterator[str] = iter(chunks)
        self.closed: bool = False

    def __enter__(self) -> "_FakeStream":
        """Returns the stream itself, like the real SDK context manager."""
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Records that the stream was closed."""
        self.closed = True


class _FakeMessages:
    """Fake ``client.messages`` namespace that records stream() calls."""

    def __init__(self, chunks: List[str]) -> None:
        """Stores canned chunks and prepares a slot for captured kwargs."""
        self._chunks = chunks
        self.last_kwargs: Dict[str, Any] = {}
        self.call_count: int = 0
        self.last_stream: Optional[_FakeStream] = None

    def stream(self, **kwargs: Any) -> _FakeStream:
        """Captures kwargs and returns a fresh fake stream."""
        self.call_count += 1
        self.last_kwargs = kwargs
        self.last_stream = _FakeStream(self._chunks)
        return self.last_stream


class _FakeAnthropic:
    """Fake ``anthropic.Anthropic`` client exposing a ``messages`` namespace."""

    def __init__(self, chunks: List[str]) -> None:
        """Wires up the fake messages namespace with canned chunks."""
        self.messages = _FakeMessages(chunks)


@pytest.fixture
def chunks() -> List[str]:
    """Canned answer chunks used across the streaming tests."""
    return ["Hello", ", ", "world", "!"]


@pytest.fixture
def fake_client(chunks: List[str]) -> _FakeAnthropic:
    """A fake Anthropic client that replays ``chunks``."""
    return _FakeAnthropic(chunks)


@pytest.fixture
def claude(fake_client: _FakeAnthropic) -> ClaudeClient:
    """A ClaudeClient wired to the injected fake Anthropic client."""
    return ClaudeClient(model="test-model", client=fake_client)


def test_stream_answer_yields_chunks_in_order(claude: ClaudeClient, chunks: List[str]) -> None:
    """stream_answer yields the fake chunks in their original order."""
    # Arrange / Act
    result = list(claude.stream_answer("What is a deadlock?"))

    # Assert
    assert result == chunks


def test_configured_model_is_passed_through(claude: ClaudeClient, fake_client: _FakeAnthropic) -> None:
    """The model given to the client is forwarded to messages.stream()."""
    # Act
    list(claude.stream_answer("Explain GIL"))

    # Assert
    assert fake_client.messages.last_kwargs["model"] == "test-model"
    assert fake_client.messages.call_count == 1


def test_default_model_comes_from_config(fake_client: _FakeAnthropic) -> None:
    """When no model is given, the client falls back to config.model."""
    # Arrange
    from src.config import config

    client = ClaudeClient(client=fake_client)

    # Act
    list(client.stream_answer("Q"))

    # Assert
    assert client.model == config.model
    assert fake_client.messages.last_kwargs["model"] == config.model


def test_system_prompt_answer_mode_wording() -> None:
    """ANSWER mode prompt asks for a short ready answer with bullet points."""
    # Act
    prompt = ClaudeClient.build_system_prompt(Mode.ANSWER)

    # Assert
    assert "ANSWER" in prompt
    assert "bullet points" in prompt
    assert str(config.answer_points) in prompt
    # Should not contain the coach-specific instruction.
    assert "supporting theses" not in prompt


def test_system_prompt_coach_mode_wording() -> None:
    """COACH mode prompt gives 3 supporting theses, not a ready answer."""
    # Act
    prompt = ClaudeClient.build_system_prompt(Mode.COACH)

    # Assert
    assert "COACH" in prompt
    assert "supporting theses" in prompt
    assert str(config.answer_points) in prompt
    assert "НЕ давай готовый ответ" in prompt
    # Should not contain the answer-specific bullet-point instruction.
    assert "bullet points" not in prompt


def test_system_prompt_differs_between_modes() -> None:
    """The system prompt is mode-specific (ANSWER != COACH)."""
    # Act
    answer_prompt = ClaudeClient.build_system_prompt(Mode.ANSWER)
    coach_prompt = ClaudeClient.build_system_prompt(Mode.COACH)

    # Assert
    assert answer_prompt != coach_prompt


@pytest.mark.parametrize("mode", [Mode.ANSWER, Mode.COACH])
def test_system_prompt_instructs_russian_and_english_terms(mode: Mode) -> None:
    """Every mode instructs Russian answers while keeping terms in English."""
    # Act
    prompt = ClaudeClient.build_system_prompt(mode)

    # Assert
    assert "русском" in prompt  # answer in Russian
    assert "English" in prompt  # technical terms stay in English


def test_system_prompt_uses_configured_answer_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """The answer-language clause follows ``config.answer_lang`` (e.g. en)."""
    # Arrange
    monkeypatch.setattr(config, "answer_lang", "en")

    # Act
    prompt = ClaudeClient.build_system_prompt(Mode.ANSWER)

    # Assert
    assert "English" in prompt
    assert "русском" not in prompt


def test_system_prompt_passed_to_stream_matches_mode(claude: ClaudeClient, fake_client: _FakeAnthropic) -> None:
    """stream_answer forwards the mode-specific system prompt to the SDK."""
    # Act
    list(claude.stream_answer("Q", mode=Mode.ANSWER))

    # Assert
    assert fake_client.messages.last_kwargs["system"] == ClaudeClient.build_system_prompt(Mode.ANSWER)


def test_default_mode_is_coach(claude: ClaudeClient, fake_client: _FakeAnthropic) -> None:
    """The default answer style is COACH when no mode is given."""
    # Act
    list(claude.stream_answer("Q"))

    # Assert
    assert fake_client.messages.last_kwargs["system"] == ClaudeClient.build_system_prompt(Mode.COACH)


def test_image_block_included_only_when_provided(claude: ClaudeClient, fake_client: _FakeAnthropic) -> None:
    """The image block is present iff image_b64 is supplied."""
    # Act: with image
    list(claude.stream_answer("Q", image_b64="QkFTRTY0UE5H"))
    content_with_image = fake_client.messages.last_kwargs["messages"][0]["content"]
    image_blocks = [block for block in content_with_image if block["type"] == "image"]

    # Assert: exactly one correctly-shaped base64 PNG image block
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": "QkFTRTY0UE5H",
    }

    # Act: without image
    list(claude.stream_answer("Q"))
    content_without_image = fake_client.messages.last_kwargs["messages"][0]["content"]

    # Assert: no image block at all
    assert all(block["type"] != "image" for block in content_without_image)


def test_context_included_when_given(claude: ClaudeClient, fake_client: _FakeAnthropic) -> None:
    """The rolling context is embedded in a text block when provided."""
    # Act
    list(claude.stream_answer("Q", context="Кандидат рассказывал про индексы"))
    content = fake_client.messages.last_kwargs["messages"][0]["content"]
    text_blocks = [block["text"] for block in content if block["type"] == "text"]

    # Assert
    assert any("Кандидат рассказывал про индексы" in text for text in text_blocks)


def test_context_absent_when_not_given(claude: ClaudeClient, fake_client: _FakeAnthropic) -> None:
    """No context text block is added when context is omitted."""
    # Act
    list(claude.stream_answer("What is a mutex?"))
    content = fake_client.messages.last_kwargs["messages"][0]["content"]
    text_blocks = [block["text"] for block in content if block["type"] == "text"]

    # Assert: question is present, context preamble is not
    assert any("What is a mutex?" in text for text in text_blocks)
    assert all("Контекст разговора" not in text for text in text_blocks)


def test_question_is_always_included(claude: ClaudeClient, fake_client: _FakeAnthropic) -> None:
    """The question text is always part of the user content."""
    # Act
    list(claude.stream_answer("Describe TCP handshake"))
    content = fake_client.messages.last_kwargs["messages"][0]["content"]
    text_blocks = [block["text"] for block in content if block["type"] == "text"]

    # Assert
    assert any("Describe TCP handshake" in text for text in text_blocks)


def test_message_role_is_user(claude: ClaudeClient, fake_client: _FakeAnthropic) -> None:
    """The single message is sent with the 'user' role."""
    # Act
    list(claude.stream_answer("Q"))

    # Assert
    messages = fake_client.messages.last_kwargs["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


def test_image_precedes_context_and_question(claude: ClaudeClient, fake_client: _FakeAnthropic) -> None:
    """When all blocks are present they are ordered image, context, question."""
    # Act
    list(
        claude.stream_answer(
            "Q",
            image_b64="aW1n",
            context="ctx",
        )
    )
    content = fake_client.messages.last_kwargs["messages"][0]["content"]

    # Assert
    assert content[0]["type"] == "image"
    assert "ctx" in content[1]["text"]
    assert "Q" in content[2]["text"]


def test_max_tokens_is_passed(claude: ClaudeClient, fake_client: _FakeAnthropic) -> None:
    """A positive max_tokens cap is forwarded to the SDK."""
    # Act
    list(claude.stream_answer("Q"))

    # Assert
    assert fake_client.messages.last_kwargs["max_tokens"] > 0


def test_stream_context_manager_is_closed(claude: ClaudeClient, fake_client: _FakeAnthropic) -> None:
    """The streaming context manager is exited (closed) after consumption."""
    # Act
    list(claude.stream_answer("Q"))

    # Assert
    assert fake_client.messages.last_stream is not None
    assert fake_client.messages.last_stream.closed is True


def test_injected_client_takes_precedence_over_api_key(fake_client: _FakeAnthropic) -> None:
    """When a client is injected, no real Anthropic client is constructed."""
    # Arrange / Act: passing an api_key alongside a client must not create a network client.
    client = ClaudeClient(api_key="should-be-ignored", client=fake_client)
    result = list(client.stream_answer("Q"))

    # Assert
    assert result  # streamed via the injected fake, not a real client
    assert client._client is fake_client  # pylint: disable=protected-access


def test_default_construction_builds_real_anthropic_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an injected client, an anthropic.Anthropic is built with the api key."""
    # Arrange
    import src.llm.claude as claude_module

    captured: Dict[str, Any] = {}

    class _DummyAnthropic:
        def __init__(self, api_key: str) -> None:
            captured["api_key"] = api_key

    monkeypatch.setattr(claude_module.anthropic, "Anthropic", _DummyAnthropic)

    # Act
    ClaudeClient(api_key="my-secret-key", model="m")

    # Assert
    assert captured["api_key"] == "my-secret-key"


def test_set_model_updates_model(fake_client: _FakeAnthropic) -> None:
    """set_model swaps the model used for subsequent requests."""
    # Arrange
    client = ClaudeClient(model="old", client=fake_client)

    # Act
    client.set_model("new")

    # Assert
    assert client.model == "new"
