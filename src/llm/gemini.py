# src/llm/gemini.py

"""Google Gemini answer client (LangChain), with streaming and screenshot vision.

This is a drop-in alternative to :class:`src.llm.claude.ClaudeClient`, selected via
``SUFLER_LLM_PROVIDER=gemini``. It targets Gemini's **free tier** (a Google AI Studio
key in ``SUFLER_GEMINI_API_KEY``) and, like the Claude client, builds a multimodal
request (optional base64-PNG screenshot + rolling context + question) and streams the
answer back token-by-token.

The heavy ``langchain_google_genai`` / ``langchain_core`` dependencies are imported
lazily so importing this module (and the test suite) never requires them. The system
prompt and answer/coach styles are shared with the Claude client via
:meth:`src.llm.claude.ClaudeClient.build_system_prompt`.
"""

from typing import Any, Iterator, List, Optional

from src.config import config
from src.helpers.logger import get_logger
from src.llm.claude import ClaudeClient
from src.models.enums import Mode

logger = get_logger(__name__)

#: Default Gemini model — fast, multimodal, free-tier eligible.
DEFAULT_GEMINI_MODEL: str = "gemini-2.0-flash"

#: Upper bound on streamed answer length (answers are intentionally short).
_MAX_TOKENS: int = 1024


class GeminiClient:
    """Streaming Gemini client tuned for the sufler prompter (free tier).

    The underlying LangChain chat model is built lazily and is injectable so tests
    never hit the network.

    Attributes:
        model (str): The Gemini model id used for every request.
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
            api_key (Optional[str]): Google AI Studio key. Defaults to
                ``config.gemini_api_key`` (from ``SUFLER_GEMINI_API_KEY``).
            model (Optional[str]): Gemini model id. Defaults to ``config.gemini_model``
                or :data:`DEFAULT_GEMINI_MODEL`.
            client (Optional[Any]): Pre-built LangChain chat model to use instead of
                constructing one. An injection point for tests; when provided,
                ``api_key`` is ignored.
        """
        self.model: str = model or config.gemini_model or DEFAULT_GEMINI_MODEL
        self._api_key: str = api_key or config.gemini_api_key
        self._client: Optional[Any] = client

    @staticmethod
    def build_system_prompt(mode: Mode) -> str:
        """Returns the shared senior-prompter system prompt for ``mode``.

        Args:
            mode (Mode): The desired answer style.

        Returns:
            str: The same system prompt the Claude client uses.
        """
        return ClaudeClient.build_system_prompt(mode)

    def _model_client(self) -> Any:
        """Builds (once) and returns the LangChain Gemini chat model.

        Returns:
            Any: A ``ChatGoogleGenerativeAI`` instance.

        Raises:
            RuntimeError: If ``langchain_google_genai`` is not installed.
        """
        if self._client is None:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI  # pylint: disable=import-outside-toplevel
            except ImportError as exc:
                raise RuntimeError(
                    "langchain-google-genai is not installed. Install it with "
                    "`pip install langchain-google-genai` to use the Gemini answer backend."
                ) from exc
            self._client = ChatGoogleGenerativeAI(
                model=self.model,
                google_api_key=self._api_key or None,
                temperature=0.0,
                max_output_tokens=_MAX_TOKENS,
            )
        return self._client

    @staticmethod
    def _build_user_content(
        question: str,
        image_b64: Optional[str],
        context: Optional[str],
    ) -> List[Any]:
        """Builds the LangChain multimodal content parts for the user message.

        Ordered image-first (so the model sees the screenshot before reading), then
        the optional rolling context, then the question.

        Args:
            question (str): The interview question to answer.
            image_b64 (Optional[str]): Base64-encoded PNG screenshot, if any.
            context (Optional[str]): Rolling conversation/speech context, if any.

        Returns:
            List[Any]: LangChain content parts for a ``HumanMessage``.
        """
        parts: List[Any] = []
        if image_b64:
            parts.append({"type": "image_url", "image_url": f"data:image/png;base64,{image_b64}"})
        if context:
            parts.append({"type": "text", "text": f"Контекст разговора:\n{context}"})
        parts.append({"type": "text", "text": f"Вопрос:\n{question}"})
        return parts

    def stream_answer(
        self,
        question: str,
        *,
        image_b64: Optional[str] = None,
        context: Optional[str] = None,
        mode: Mode = Mode.COACH,
    ) -> Iterator[str]:
        """Streams Gemini's answer to a question token-by-token.

        Args:
            question (str): The interview question to answer.
            image_b64 (Optional[str]): Optional base64-encoded PNG screenshot.
            context (Optional[str]): Optional rolling speech/conversation context.
            mode (Mode): Answer style. Defaults to :attr:`Mode.COACH`.

        Yields:
            str: Successive text chunks of the answer as they stream in.
        """
        from langchain_core.messages import HumanMessage, SystemMessage  # pylint: disable=import-outside-toplevel

        messages = [
            SystemMessage(content=self.build_system_prompt(mode)),
            HumanMessage(content=self._build_user_content(question, image_b64, context)),
        ]
        logger.info(
            "Streaming Gemini answer (model=%s, mode=%s, image=%s, context=%s)",
            self.model,
            mode.value,
            image_b64 is not None,
            context is not None,
        )
        for chunk in self._model_client().stream(messages):
            yield from self._chunk_text(chunk.content)

    @staticmethod
    def _chunk_text(content: Any) -> Iterator[str]:
        """Extracts plain-text pieces from a LangChain message chunk's content.

        Gemini streams ``str`` deltas, but LangChain content can also be a list of
        parts; both shapes are flattened to non-empty text.

        Args:
            content (Any): ``chunk.content`` — a ``str`` or a list of parts.

        Yields:
            str: Non-empty text pieces.
        """
        if isinstance(content, str):
            if content:
                yield content
            return
        if isinstance(content, list):
            for part in content:
                if isinstance(part, str) and part:
                    yield part
                elif isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        yield text
