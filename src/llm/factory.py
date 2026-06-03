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


class AnswerClient(Protocol):  # pylint: disable=too-few-public-methods
    """Minimal interface every answer backend implements."""

    def stream_answer(
        self,
        question: str,
        *,
        image_b64: Optional[str] = None,
        context: Optional[str] = None,
        mode: Mode = Mode.COACH,
    ) -> Iterator[str]:
        """Streams the answer to a question token-by-token."""


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
    raise ValueError(f"Unknown LLM provider {selected!r}. Valid options are: claude, gemini.")
