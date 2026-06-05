# src/core/controller.py
# pylint: disable=no-name-in-module,c-extension-no-member

"""Controller that wires inputs to the overlay, screenshot, Claude and context.

All three entry points — the global hotkey, the overlay's "📸 Скрин" button and
manual text input — funnel into one streaming flow (see SUFLER_SPEC.md). The
Claude call runs on a worker thread; tokens reach the overlay through a Qt signal
so the UI is updated on the main thread and never blocks.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, Optional, Protocol

from PyQt6 import QtWidgets
from PyQt6.QtCore import QObject, pyqtSignal

from src.audio.system_volume import set_input_volume as default_set_input_volume
from src.config import config
from src.core.context import RollingContext
from src.helpers.logger import get_logger
from src.llm.factory import AnswerClient
from src.models.enums import Mode
from src.ui.overlay import Overlay
from src.vision.screenshot import grab_screen as default_grab_screen

logger = get_logger(__name__)

# Prompt used when the question lives in the screenshot rather than in typed text.
CAPTURE_PROMPT = "Ответь кратко на вопрос или задачу, показанную на скриншоте экрана."
HIDE_BEFORE_CAPTURE_SECONDS = 0.15

#: Interrogatives that mark a recognized utterance as a question worth auto-answering.
_QUESTION_WORDS: frozenset[str] = frozenset(
    {
        # ru
        "что",
        "как",
        "почему",
        "зачем",
        "чем",
        "какой",
        "какая",
        "какие",
        "какое",
        "кто",
        "где",
        "когда",
        "сколько",
        "куда",
        "откуда",
        "расскажи",
        "объясни",
        "назови",
        "перечисли",
        "опиши",
        "сравни",
        "в чём",
        "чём",
        "зачём",
        # en
        "what",
        "how",
        "why",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "explain",
        "describe",
        "compare",
        "tell",
        "name",
        "list",
        "define",
    }
)


def _looks_like_question(text: str) -> bool:
    """Heuristic: does a recognized utterance look like a question worth answering?

    True when it ends with ``?`` or starts with a known interrogative/imperative word.
    This filters out the long statements of a monologue so the prompter answers actual
    questions instead of every speech chunk.

    Args:
        text (str): The recognized utterance.

    Returns:
        bool: ``True`` if the text looks like a question/request.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if "?" in stripped:
        return True
    first = stripped.lower().lstrip("«\"'(-—. ").split(maxsplit=1)[:1]
    return bool(first) and first[0].strip(".,!:;") in _QUESTION_WORDS


def _extract_terms_from_speech(text: str) -> list[str]:
    """Heuristically extracts technical terms from recognized speech for the tag cloud.

    No LLM: picks out Latin-script tokens (≥3 chars) — in Russian interview speech these
    are the technical terms (``REST``, ``deadlock``, ``thread``, ``GIL`` …). Returns them
    in order of first appearance; the tag cloud de-duplicates and caps the list.

    Args:
        text (str): The recognized utterance.

    Returns:
        list[str]: Candidate terms, in order of appearance.
    """
    seen: set[str] = set()
    terms: list[str] = []
    for match in re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{2,}", text):
        key = match.lower()
        if key not in seen:
            seen.add(key)
            terms.append(match)
    return terms


Runner = Callable[[Callable[[], None]], None]


class SpeechControl(Protocol):  # pylint: disable=too-few-public-methods
    """Minimal interface for pausing/resuming live speech capture."""

    def set_listening(self, listening: bool) -> None:
        """Resumes (``True``) or pauses (``False``) live listening."""


class Controller(QObject):
    """Orchestrates input → (screenshot) → context → Claude → overlay streaming."""

    answer_token = pyqtSignal(str)
    partial_speech = pyqtSignal(str)
    final_speech = pyqtSignal(str)
    speech_level = pyqtSignal(float)
    stream_finished = pyqtSignal()
    background_answer = pyqtSignal(str, str)  # (question, raw answer) produced while pinned

    def __init__(
        self,
        overlay: Overlay,
        claude: AnswerClient,
        context: RollingContext,
        *,
        grab_screen: Callable[[], str] = default_grab_screen,
        mode: Mode = Mode.COACH,
        runner: Optional[Runner] = None,
        hide_delay: float = HIDE_BEFORE_CAPTURE_SECONDS,
        set_input_volume: Callable[[int], bool] = default_set_input_volume,
        auto_answer: bool = True,
    ) -> None:
        """Wires the controller to its collaborators.

        Args:
            overlay (Overlay): The stealth overlay to drive.
            claude (AnswerClient): The streaming answer client (Claude or Gemini).
            context (RollingContext): The rolling conversation context.
            grab_screen (Callable[[], str]): Screen-capture function returning base64 PNG.
            mode (Mode): Initial answer mode.
            runner (Optional[Runner]): Executes the streaming work; defaults to a
                daemon thread. Tests inject a synchronous runner.
            hide_delay (float): Seconds to wait after hiding the overlay before capture.
            set_input_volume (Callable[[int], bool]): Applies a system microphone
                volume (0..100); defaults to the macOS ``osascript`` implementation.
        """
        super().__init__()
        self._overlay = overlay
        self._claude = claude
        self._context = context
        self._grab_screen = grab_screen
        self.mode = mode
        self._runner: Runner = runner or self._spawn_thread
        self._hide_delay = hide_delay
        self._set_input_volume = set_input_volume
        self.auto_answer = auto_answer
        #: When pinned, the visible answer is frozen and new auto-answers queue forward.
        self._pinned: bool = False
        #: Monotonic time of the last auto-answer (drives the cooldown).
        self._last_auto_answer: float = 0.0
        self._speech: Optional[SpeechControl] = None
        #: Drill-down history: (question, raw answer) of screens we can go back to.
        self._nav_stack: list[tuple[str, str]] = []
        #: Screens we returned from and can go forward to (browser-style redo).
        self._fwd_stack: list[tuple[str, str]] = []
        self._current_question: str = ""
        self.answer_token.connect(self._overlay.append_answer)
        self.partial_speech.connect(self._on_partial_speech)
        self.final_speech.connect(self._on_final_speech)
        self.speech_level.connect(self._overlay.set_input_level)
        self.stream_finished.connect(self._overlay.end_answer)
        self.background_answer.connect(self._on_background_answer)

    # ------------------------------------------------------------------ #
    # Entry points (the single "on_capture" surface from the spec)
    # ------------------------------------------------------------------ #
    def on_capture(self) -> None:
        """Hotkey/button entry: screenshot the screen and stream an answer."""
        logger.info("on_capture")
        image_b64 = self._capture_screenshot()
        self._context.set_screenshot(image_b64)
        self._overlay.set_question("📸 Скриншот экрана")
        self._navigate_to("📸 Скриншот экрана")
        self._start_stream(CAPTURE_PROMPT, image_b64=image_b64)

    def on_submit_text(self, text: str) -> None:
        """Manual-input entry: stream an answer to typed text (no screenshot)."""
        question = text.strip()
        if not question:
            return
        # A single bare word is treated as "what is …?" (a definition lookup).
        if " " not in question and "?" not in question:
            prefix = "What is" if config.answer_lang.strip().lower() == "en" else "Что такое"
            question = f"{prefix} {question}?"
        logger.info("on_submit_text (%d chars)", len(question))
        self._context.set_question(question)
        self._overlay.set_question(question)
        self._navigate_to(question)
        self._start_stream(question, image_b64=None)

    def on_answer_last(self) -> None:
        """Hotkey entry: answer using the recent speech / last question context."""
        question = self._context.recent_speech() or (self._context.last_question() or "")
        if not question:
            logger.info("on_answer_last: no context yet")
            self._overlay.set_question("(нет распознанной речи)")
            return
        self._overlay.set_question(question)
        self._navigate_to(question)
        self._start_stream(question, image_b64=None)

    def panic(self) -> None:
        """Instantly hide the overlay (panic)."""
        self._overlay.panic_hide()

    def set_mode(self, mode: Mode) -> None:
        """Switch the answer mode and reflect it in the overlay."""
        self.mode = mode
        self._overlay.set_mode(mode)

    def on_model_changed(self, model: str) -> None:
        """Switches the answer model chosen in the UI selector.

        Args:
            model (str): The new model id.
        """
        model = model.strip()
        if not model:
            return
        logger.info("Model changed -> %s", model)
        self._claude.set_model(model)

    def on_language_changed(self, language: str) -> None:
        """Sets the output language the model should answer in (e.g. ``ru`` / ``en``).

        Args:
            language (str): The answer language code.
        """
        language = language.strip().lower()
        if not language:
            return
        logger.info("Answer language -> %s", language)
        config.answer_lang = language

    def on_term_clicked(self, term: str) -> None:
        """Drill-down: answer a clicked term, pushing the current screen onto the back stack.

        Args:
            term (str): The bold phrase clicked in the current answer.
        """
        term = term.strip()
        if not term:
            return
        logger.info("on_term_clicked: %r", term)
        question = f"Расскажи подробнее про: {term}"
        self._context.set_question(question)
        self._overlay.set_question(question)
        self._navigate_to(question)
        self._start_stream(question, image_b64=None)

    def on_back(self) -> None:
        """Navigate back: restore the previous answer; current goes to forward history."""
        if not self._nav_stack:
            return
        self._fwd_stack.append((self._current_question, self._overlay.answer_raw()))
        self._restore(self._nav_stack.pop())

    def on_forward(self) -> None:
        """Navigate forward to a screen we returned from; current goes to back history."""
        if not self._fwd_stack:
            return
        self._nav_stack.append((self._current_question, self._overlay.answer_raw()))
        self._restore(self._fwd_stack.pop())

    def _restore(self, screen: tuple[str, str]) -> None:
        """Displays a saved (question, raw answer) screen and refreshes the nav buttons."""
        question, answer_raw = screen
        self._current_question = question
        self._overlay.set_question(question)
        self._overlay.show_answer(answer_raw)
        self._update_nav_buttons()

    def _navigate_to(self, question: str) -> None:
        """Advances to a new screen, keeping the current one in back history.

        Browser-style: the current screen (if any) is pushed onto the back stack and
        the forward stack is cleared, so a new question/drill-down does not erase the
        history of previous hints — back returns to them.

        Args:
            question (str): The question for the new screen.
        """
        if self._current_question:
            self._nav_stack.append((self._current_question, self._overlay.answer_raw()))
        self._fwd_stack.clear()
        self._current_question = question
        self._update_nav_buttons()

    def _update_nav_buttons(self) -> None:
        """Syncs the back/forward buttons to the navigation stacks."""
        self._overlay.set_back_visible(bool(self._nav_stack))
        self._overlay.set_forward_visible(bool(self._fwd_stack))

    def set_speech_pipeline(self, pipeline: SpeechControl) -> None:
        """Attaches the live-speech pipeline so the mic toggle can pause/resume it.

        Args:
            pipeline (SpeechControl): The running speech pipeline (anything exposing
                ``set_listening``).
        """
        self._speech = pipeline

    def on_mic_toggled(self, listening: bool) -> None:
        """Mic-button entry: pause or resume live speech capture.

        Args:
            listening (bool): ``True`` resumes listening; ``False`` pauses it. A no-op
                when no speech pipeline is attached (STT unavailable).
        """
        logger.info("Microphone %s", "on" if listening else "off")
        if self._speech is not None:
            self._speech.set_listening(listening)

    def on_input_volume_changed(self, percent: int) -> None:
        """Mic-volume slider entry: apply a new system input volume.

        Args:
            percent (int): Desired microphone input volume in percent (0..100).
        """
        logger.info("Input volume -> %d%%", percent)
        self._set_input_volume(percent)

    # ------------------------------------------------------------------ #
    # Live speech (STT) slots — invoked on the UI thread via signals
    # ------------------------------------------------------------------ #
    def _on_partial_speech(self, text: str) -> None:
        """Shows live (draft) recognised speech in the question field (unless pinned)."""
        if not self._pinned:
            self._overlay.set_question(text)

    def _on_final_speech(self, text: str) -> None:
        """Records a finalised utterance, then auto-answers it when enabled.

        Args:
            text (str): The finalized recognized utterance.
        """
        self._context.add_speech(text)
        self._context.set_question(text)
        self._overlay.append_transcript(text)  # recognition feed keeps flowing even when pinned
        # Task 1 (always, no LLM): surface technical terms from speech into the tag cloud.
        terms = _extract_terms_from_speech(text)
        if terms:
            self._overlay.add_tags(terms)
        if not self._pinned:
            self._overlay.set_question(text)
        # Task 2: answer actual questions (LLM, gated by the question filter + cooldown).
        if self._should_auto_answer(text):
            self._last_auto_answer = time.monotonic()
            if self._pinned:
                # Don't disturb the frozen answer; compute in the background and queue forward.
                self._start_stream_background(text)
            else:
                self._navigate_to(text)
                self._start_stream(text, image_b64=None)

    def _should_auto_answer(self, text: str) -> bool:
        """Decides whether a recognized utterance should be auto-answered.

        Gated by: auto-answer enabled, the question filter (skip monologue statements
        unless it looks like a question), and a cooldown so a burst of speech does not
        spam the LLM (free-tier rate limits).

        Args:
            text (str): The finalized recognized utterance.

        Returns:
            bool: ``True`` if an answer should be streamed for ``text``.
        """
        if not self.auto_answer:
            return False
        if config.answer_questions_only and not _looks_like_question(text):
            logger.debug("Skipping auto-answer (not a question): %r", text[:60])
            return False
        if time.monotonic() - self._last_auto_answer < config.answer_cooldown_seconds:
            logger.debug("Skipping auto-answer (cooldown active)")
            return False
        return True

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _capture_screenshot(self) -> Optional[str]:
        """Hide the overlay, grab the screen, then restore the overlay.

        Returns:
            Optional[str]: Base64-encoded PNG, or ``None`` if capture failed.
        """
        self._overlay.hide()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.processEvents()
        if self._hide_delay > 0:
            time.sleep(self._hide_delay)
        try:
            return self._grab_screen()
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            logger.exception("Screenshot capture failed")
            return None
        finally:
            self._overlay.show()

    def set_pinned(self, pinned: bool) -> None:
        """Freezes/unfreezes the visible answer.

        While pinned, auto-answers are computed in the background and appended to the
        forward history (reachable with → / :meth:`on_forward`) instead of replacing
        the frozen answer.

        Args:
            pinned (bool): ``True`` to freeze the current answer.
        """
        self._pinned = pinned
        self._overlay.set_pinned(pinned)
        logger.info("Pin %s", "on" if pinned else "off")

    def _start_stream_background(self, question: str) -> None:
        """Streams an answer without touching the visible area; queues it forward when done."""
        context_text = self._context.render() or None

        def work() -> None:
            tokens: list[str] = []
            try:
                for token in self._claude.stream_answer(question, image_b64=None, context=context_text, mode=self.mode):
                    tokens.append(token)
            except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                logger.exception("Background answer stream failed")
                return
            self.background_answer.emit(question, "".join(tokens))

        self._runner(work)

    def _on_background_answer(self, question: str, raw: str) -> None:
        """Queues a background (pinned) answer onto forward history, oldest revealed first."""
        self._fwd_stack.insert(0, (question, raw))
        self._update_nav_buttons()

    def _start_stream(self, question: str, *, image_b64: Optional[str]) -> None:
        """Begin a fresh answer and stream Claude tokens into the overlay."""
        self._overlay.begin_answer()
        context_text = self._context.render() or None

        def work() -> None:
            try:
                for token in self._claude.stream_answer(
                    question, image_b64=image_b64, context=context_text, mode=self.mode
                ):
                    self.answer_token.emit(token)
            except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                logger.exception("Answer stream failed")
                self.answer_token.emit("[ошибка запроса к LLM]")
            finally:
                self.stream_finished.emit()

        self._runner(work)

    @staticmethod
    def _spawn_thread(work: Callable[[], None]) -> None:
        """Run ``work`` on a daemon thread (default production runner)."""
        threading.Thread(target=work, daemon=True).start()
