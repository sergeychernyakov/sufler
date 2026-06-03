# tests/llm/test_factory.py

"""Unit tests for :mod:`src.llm.factory` (answer-client provider selection)."""

import pytest

from src.llm import factory
from src.llm.claude import ClaudeClient
from src.llm.factory import create_answer_client
from src.llm.gemini import GeminiClient
from src.llm.groq import GroqClient


def test_create_claude_client_for_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """``llm_provider == 'claude'`` builds a ``ClaudeClient``."""
    # Arrange
    monkeypatch.setattr(factory.config, "llm_provider", "claude")

    # Act / Assert
    assert isinstance(create_answer_client(), ClaudeClient)


def test_create_gemini_client_for_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """``llm_provider == 'gemini'`` builds a ``GeminiClient`` (no network/model yet)."""
    # Arrange
    monkeypatch.setattr(factory.config, "llm_provider", "gemini")

    # Act / Assert
    assert isinstance(create_answer_client(), GeminiClient)


def test_create_groq_client_for_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """``llm_provider == 'groq'`` builds a ``GroqClient`` (no network/model yet)."""
    # Arrange
    monkeypatch.setattr(factory.config, "llm_provider", "groq")

    # Act / Assert
    assert isinstance(create_answer_client(), GroqClient)


def test_explicit_provider_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit ``provider`` argument wins over ``config.llm_provider``."""
    # Arrange
    monkeypatch.setattr(factory.config, "llm_provider", "gemini")

    # Act / Assert
    assert isinstance(create_answer_client("claude"), ClaudeClient)


def test_provider_value_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider matching ignores case and surrounding whitespace."""
    # Arrange
    monkeypatch.setattr(factory.config, "llm_provider", "  GEMINI ")

    # Act / Assert
    assert isinstance(create_answer_client(), GeminiClient)


def test_unknown_provider_raises_value_error() -> None:
    """An unrecognised provider raises ``ValueError``."""
    # Act / Assert
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        create_answer_client("does-not-exist")


def test_available_models_lists_provider_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """``available_models`` returns the curated list for the configured provider."""
    monkeypatch.setattr(factory.config, "llm_provider", "groq")
    assert "llama-3.3-70b-versatile" in factory.available_models()


def test_current_model_returns_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """``current_model`` returns the configured model id for the provider."""
    monkeypatch.setattr(factory.config, "llm_provider", "groq")
    monkeypatch.setattr(factory.config, "groq_model", "the-model")
    assert factory.current_model() == "the-model"
