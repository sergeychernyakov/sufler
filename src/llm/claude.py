# src/llm/claude.py

"""Anthropic Claude client with token-by-token streaming and answer/coach modes.

This module wraps the Anthropic Messages API for the sufler prompter (Phase 2).
It builds a multimodal request from an interview question, an optional screenshot
(base64 PNG) and rolling speech context, then streams the model's answer back as a
generator of text chunks so the UI can render tokens as they arrive.

Two answer styles are supported via :class:`src.models.enums.Mode`:

* ``Mode.ANSWER`` — a short, ready-to-read answer (2–4 terse bullet points).
* ``Mode.COACH`` — *not* a ready answer, but 3 supporting theses so the candidate
  formulates the reply in their own words.

The system prompt always instructs the model to reply in Russian while keeping
technical terms in English.
"""

from typing import Any, Dict, Iterator, List, Optional

import anthropic

from src.config import config
from src.helpers.logger import get_logger
from src.models.enums import Mode

logger = get_logger(__name__)

# Upper bound on streamed answer length. Answers are intentionally short, so a
# modest cap keeps latency low and stops the model rambling past the format.
_MAX_TOKENS: int = 1024

#: Output-language clause, keyed by ``SUFLER_ANSWER_LANG``.
_LANGUAGE_CLAUSE: Dict[str, str] = {
    "ru": "русском языке (Russian)",
    "en": "English",
}

_BASE_SYSTEM_PROMPT: str = (
    "Ты — опытный senior-level суфлёр на техническом собеседовании. "
    "Отвечай на {lang}, но все технические термины оставляй на "
    "English (например: thread, deadlock, index, garbage collector). "
    "Будь точным и по существу, без воды и вводных фраз."
)

_ANSWER_INSTRUCTIONS: str = (
    "Режим ANSWER: дай краткий готовый ответ в виде до {points} предельно сжатых пунктов "
    "(bullet points). Каждый пункт — одна короткая мысль, которую можно сразу "
    "произнести вслух. Не добавляй вступления, пояснения или заключение."
)

_COACH_INSTRUCTIONS: str = (
    "Режим COACH: НЕ давай готовый ответ. "
    "Вместо этого дай ровно {points} тезисов-опор ({points} supporting theses), "
    "чтобы человек сформулировал ответ сам своими словами. "
    "Тезисы — это направления и ключевые слова, а не развёрнутые формулировки."
)

_MODE_INSTRUCTIONS: Dict[Mode, str] = {
    Mode.ANSWER: _ANSWER_INSTRUCTIONS,
    Mode.COACH: _COACH_INSTRUCTIONS,
}


class ClaudeClient:
    """Streaming client for Anthropic Claude tuned for the sufler prompter.

    The underlying ``anthropic.Anthropic`` instance is injectable so tests (and
    callers that want a custom transport) never have to hit the network.

    Attributes:
        model (str): The Claude model id used for every request.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        *,
        client: Optional[Any] = None,
    ) -> None:
        """Initialises the client.

        Args:
            api_key (Optional[str]): Anthropic API key. Defaults to
                ``config.anthropic_api_key`` (sourced from the environment).
            model (Optional[str]): Claude model id. Defaults to ``config.model``.
            client (Optional[Any]): Pre-built Anthropic client to use instead of
                constructing one. Primarily an injection point for tests; when
                provided, ``api_key`` is ignored.
        """
        self.model: str = model or config.model
        if client is not None:
            self._client: Any = client
        else:
            self._client = anthropic.Anthropic(api_key=api_key or config.anthropic_api_key or "MISSING_API_KEY")

    def set_model(self, model: str) -> None:
        """Switches the Claude model used for subsequent requests.

        Args:
            model (str): The new Claude model id.
        """
        self.model = model

    @staticmethod
    def build_system_prompt(mode: Mode) -> str:
        """Builds the system prompt for the given answer mode.

        Args:
            mode (Mode): The desired answer style.

        Returns:
            str: The base senior-prompter persona combined with mode-specific
            formatting instructions.
        """
        lang = (config.answer_lang or "ru").strip().lower()
        base = _BASE_SYSTEM_PROMPT.format(lang=_LANGUAGE_CLAUSE.get(lang, _LANGUAGE_CLAUSE["ru"]))
        instructions = _MODE_INSTRUCTIONS[mode].format(points=config.answer_points)
        return f"{base}\n\n{instructions}"

    @staticmethod
    def _build_content(
        question: str,
        image_b64: Optional[str],
        context: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Builds the multimodal content blocks for a single user message.

        The blocks are ordered image-first (when present) so the model sees the
        visual context before reading, followed by the optional rolling speech
        context and finally the question itself.

        Args:
            question (str): The interview question to answer.
            image_b64 (Optional[str]): Base64-encoded PNG screenshot, if any.
            context (Optional[str]): Rolling conversation/speech context, if any.

        Returns:
            List[Dict[str, Any]]: Anthropic content blocks for the message.
        """
        blocks: List[Dict[str, Any]] = []

        if image_b64:
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_b64,
                    },
                }
            )

        if context:
            blocks.append({"type": "text", "text": f"Контекст разговора:\n{context}"})

        blocks.append({"type": "text", "text": f"Вопрос:\n{question}"})
        return blocks

    def stream_answer(
        self,
        question: str,
        *,
        image_b64: Optional[str] = None,
        context: Optional[str] = None,
        mode: Mode = Mode.COACH,
    ) -> Iterator[str]:
        """Streams the model's answer to a question token-by-token.

        Args:
            question (str): The interview question to answer.
            image_b64 (Optional[str]): Optional base64-encoded PNG screenshot to
                attach as an image block.
            context (Optional[str]): Optional rolling speech/conversation context.
            mode (Mode): Answer style. Defaults to :attr:`Mode.COACH`.

        Yields:
            str: Successive text chunks of the answer as they stream in.
        """
        system_prompt = self.build_system_prompt(mode)
        content = self._build_content(question, image_b64, context)
        messages: List[Dict[str, Any]] = [{"role": "user", "content": content}]

        logger.info(
            "Streaming Claude answer (model=%s, mode=%s, image=%s, context=%s)",
            self.model,
            mode.value,
            image_b64 is not None,
            context is not None,
        )

        with self._client.messages.stream(
            model=self.model,
            max_tokens=_MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        ) as stream:
            yield from stream.text_stream
