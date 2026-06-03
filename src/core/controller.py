# src/core/controller.py
# pylint: disable=no-name-in-module,c-extension-no-member

"""Controller that wires inputs to the overlay, screenshot, Claude and context.

All three entry points — the global hotkey, the overlay's "📸 Скрин" button and
manual text input — funnel into one streaming flow (see SUFLER_SPEC.md). The
Claude call runs on a worker thread; tokens reach the overlay through a Qt signal
so the UI is updated on the main thread and never blocks.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Protocol

from PyQt6 import QtWidgets
from PyQt6.QtCore import QObject, pyqtSignal

from src.core.context import RollingContext
from src.helpers.logger import get_logger
from src.llm.claude import ClaudeClient
from src.models.enums import Mode
from src.ui.overlay import Overlay
from src.vision.screenshot import grab_screen as default_grab_screen

logger = get_logger(__name__)

# Prompt used when the question lives in the screenshot rather than in typed text.
CAPTURE_PROMPT = "Ответь кратко на вопрос или задачу, показанную на скриншоте экрана."
HIDE_BEFORE_CAPTURE_SECONDS = 0.15

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

    def __init__(
        self,
        overlay: Overlay,
        claude: ClaudeClient,
        context: RollingContext,
        *,
        grab_screen: Callable[[], str] = default_grab_screen,
        mode: Mode = Mode.COACH,
        runner: Optional[Runner] = None,
        hide_delay: float = HIDE_BEFORE_CAPTURE_SECONDS,
    ) -> None:
        """Wires the controller to its collaborators.

        Args:
            overlay (Overlay): The stealth overlay to drive.
            claude (ClaudeClient): The streaming Claude client.
            context (RollingContext): The rolling conversation context.
            grab_screen (Callable[[], str]): Screen-capture function returning base64 PNG.
            mode (Mode): Initial answer mode.
            runner (Optional[Runner]): Executes the streaming work; defaults to a
                daemon thread. Tests inject a synchronous runner.
            hide_delay (float): Seconds to wait after hiding the overlay before capture.
        """
        super().__init__()
        self._overlay = overlay
        self._claude = claude
        self._context = context
        self._grab_screen = grab_screen
        self.mode = mode
        self._runner: Runner = runner or self._spawn_thread
        self._hide_delay = hide_delay
        self._speech: Optional[SpeechControl] = None
        self.answer_token.connect(self._overlay.append_answer)
        self.partial_speech.connect(self._on_partial_speech)
        self.final_speech.connect(self._on_final_speech)

    # ------------------------------------------------------------------ #
    # Entry points (the single "on_capture" surface from the spec)
    # ------------------------------------------------------------------ #
    def on_capture(self) -> None:
        """Hotkey/button entry: screenshot the screen and stream an answer."""
        logger.info("on_capture")
        image_b64 = self._capture_screenshot()
        self._context.set_screenshot(image_b64)
        self._overlay.set_question("📸 Скриншот экрана")
        self._start_stream(CAPTURE_PROMPT, image_b64=image_b64)

    def on_submit_text(self, text: str) -> None:
        """Manual-input entry: stream an answer to typed text (no screenshot)."""
        question = text.strip()
        if not question:
            return
        logger.info("on_submit_text (%d chars)", len(question))
        self._context.set_question(question)
        self._overlay.set_question(question)
        self._start_stream(question, image_b64=None)

    def on_answer_last(self) -> None:
        """Hotkey entry: answer using the recent speech / last question context."""
        question = self._context.recent_speech() or (self._context.last_question() or "")
        if not question:
            logger.info("on_answer_last: no context yet")
            self._overlay.set_question("(нет распознанной речи)")
            return
        self._overlay.set_question(question)
        self._start_stream(question, image_b64=None)

    def panic(self) -> None:
        """Instantly hide the overlay (panic)."""
        self._overlay.panic_hide()

    def set_mode(self, mode: Mode) -> None:
        """Switch the answer mode and reflect it in the overlay."""
        self.mode = mode
        self._overlay.set_mode(mode)

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

    # ------------------------------------------------------------------ #
    # Live speech (STT) slots — invoked on the UI thread via signals
    # ------------------------------------------------------------------ #
    def _on_partial_speech(self, text: str) -> None:
        """Shows live (draft) recognised speech in the question field."""
        self._overlay.set_question(text)

    def _on_final_speech(self, text: str) -> None:
        """Records a finalised utterance into the rolling context and transcript."""
        self._context.add_speech(text)
        self._context.set_question(text)
        self._overlay.set_question(text)
        self._overlay.append_transcript(text)

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
                logger.exception("Claude stream failed")
                self.answer_token.emit("[ошибка запроса к Claude]")

        self._runner(work)

    @staticmethod
    def _spawn_thread(work: Callable[[], None]) -> None:
        """Run ``work`` on a daemon thread (default production runner)."""
        threading.Thread(target=work, daemon=True).start()
