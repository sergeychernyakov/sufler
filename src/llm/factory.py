# src/llm/factory.py

"""Selects the answer LLM backend (Claude or Gemini) from configuration.

This is the single place the answer provider is chosen, keyed by
``config.llm_provider`` (``SUFLER_LLM_PROVIDER``) — mirroring how the STT engine is
selected in :func:`src.audio.stt.create_engine`. Provider client modules are imported
lazily so selecting Claude never imports the Gemini/LangChain stack, and vice versa.
"""

from typing import Iterator, Optional, Protocol

from src.config import config
from src.helpers.logger import get_logger
from src.models.enums import Mode

logger = get_logger(__name__)


class AnswerClient(Protocol):
    """Minimal interface every answer backend implements."""

    model: str

    def stream_answer(
        self,
        question: str,
        *,
        image_b64: Optional[str] = None,
        context: Optional[str] = None,
        mode: Mode = Mode.COACH,
    ) -> Iterator[str]:
        """Streams the answer to a question token-by-token."""

    def set_model(self, model: str) -> None:
        """Switches the model used for subsequent answers."""


#: Curated model ids offered in the in-app selector, per provider (free tiers first).
AVAILABLE_MODELS: dict[str, tuple[str, ...]] = {
    "claude": ("claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5"),
    "gemini": ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"),
    "groq": (
        "openai/gpt-oss-120b",
        "llama-3.3-70b-versatile",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "qwen/qwen3-32b",
        "llama-3.1-8b-instant",
    ),
}


def available_models(provider: Optional[str] = None) -> tuple[str, ...]:
    """Returns the curated model ids for the given (or configured) provider.

    Args:
        provider (Optional[str]): Provider key; ``None`` uses ``config.llm_provider``.

    Returns:
        tuple[str, ...]: Offered model ids (empty for an unknown provider).
    """
    key = (provider or config.llm_provider or "claude").strip().lower()
    return AVAILABLE_MODELS.get(key, ())


def current_model(provider: Optional[str] = None) -> str:
    """Returns the configured model id for the given (or configured) provider.

    Args:
        provider (Optional[str]): Provider key; ``None`` uses ``config.llm_provider``.

    Returns:
        str: The configured model id for that provider.
    """
    key = (provider or config.llm_provider or "claude").strip().lower()
    return {"claude": config.model, "gemini": config.gemini_model, "groq": config.groq_model}.get(key, "")


def create_answer_client(provider: Optional[str] = None) -> AnswerClient:
    """Creates the configured answer client.

    Args:
        provider (Optional[str]): ``"claude"`` or ``"gemini"``. ``None`` falls back to
            ``config.llm_provider``.

    Returns:
        AnswerClient: A ready-to-use streaming answer client.

    Raises:
        ValueError: If ``provider`` is not a recognised value.
    """
    selected = (provider or config.llm_provider or "claude").strip().lower()
    logger.info("Creating answer client: provider=%s", selected)

    if selected == "claude":
        from src.llm.claude import ClaudeClient  # pylint: disable=import-outside-toplevel

        return ClaudeClient()
    if selected == "gemini":
        from src.llm.gemini import GeminiClient  # pylint: disable=import-outside-toplevel

        return GeminiClient()
    if selected == "groq":
        from src.llm.groq import GroqClient  # pylint: disable=import-outside-toplevel

        return GroqClient()
    raise ValueError(f"Unknown LLM provider {selected!r}. Valid options are: claude, gemini, groq.")
