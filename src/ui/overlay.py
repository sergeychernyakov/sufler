# src/ui/overlay.py

"""PyQt6 stealth overlay for the sufler interview prompter (Phase 1).

The overlay is a frameless, always-on-top, semi-transparent window that shows
the recognized interview question (top, small) and the streamed answer
(bottom). It exposes a small, controller-friendly API plus mandatory stealth
controls: opacity cycling, click-through, compact mode, auto-hide and a panic
hide.

In this phase there is no real LLM: :func:`demo` streams a placeholder answer
token-by-token via a :class:`~PyQt6.QtCore.QTimer` to prove the wiring works
visually.
"""

from __future__ import annotations

import sys
from typing import Final

# PyQt6 ships compiled C extensions that pylint cannot introspect statically,
# so it falsely reports missing names/members. Static type checking is handled
# by mypy instead; silence the unavoidable C-extension noise here.
# pylint: disable=no-name-in-module,c-extension-no-member
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal

from src.helpers.logger import get_logger
from src.models.enums import Mode

logger = get_logger(__name__)

# Stealth opacity levels (percent) cycled by ``cycle_opacity``.
OPACITY_LEVELS: Final[tuple[int, ...]] = (20, 40, 70)

# Default auto-hide window (seconds); the spec asks for 10-15 s.
DEFAULT_AUTO_HIDE_SECONDS: Final[float] = 12.0

# Placeholder answer streamed token-by-token by the demo (Phase 1, no LLM).
MOCK_ANSWER_TOKENS: Final[tuple[str, ...]] = (
    "This ",
    "is ",
    "a ",
    "mocked ",
    "answer ",
    "streamed ",
    "token ",
    "by ",
    "token ",
    "via ",
    "QTimer.",
)


class Overlay(QtWidgets.QWidget):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Frameless, always-on-top stealth overlay widget.

    The widget renders two stacked text areas (question and answer), a capture
    button and a permanent manual-input field. It is meant to be driven by an
    external controller via :pyattr:`capture_requested` / :pyattr:`text_submitted`
    and the public setter/streaming methods.

    Signals:
        capture_requested: Emitted when the "📸 Скрин" button is pressed.
        text_submitted (str): Emitted with the (non-empty) manual input text
            when the user presses Enter in the input field.
    """

    capture_requested = pyqtSignal()
    text_submitted = pyqtSignal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None, *, stealth: bool = False) -> None:
        """Builds the overlay window and lays out widgets.

        Args:
            parent (QtWidgets.QWidget | None): Optional Qt parent widget.
            stealth (bool): ``True`` builds a frameless, translucent, always-on-top
                overlay kept out of the Dock. ``False`` (default) builds a normal
                window with a native title bar (drag + close button).
        """
        super().__init__(parent)

        self._stealth: bool = stealth
        self._opacity_index: int = len(OPACITY_LEVELS) - 1  # start at 70 %
        self._click_through: bool = False
        self._compact: bool = False
        self._drag_offset: QtCore.QPoint | None = None

        # Single-shot timer used by ``arm_auto_hide``.
        self._auto_hide_timer = QtCore.QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.panic_hide)

        self._build_window()
        self._build_widgets()
        self._build_layout()
        self._connect_signals()

        if self._stealth:
            self.set_opacity_percent(OPACITY_LEVELS[self._opacity_index])
        logger.debug("Overlay initialized (stealth=%s)", self._stealth)

    # ------------------------------------------------------------------ #
    # Construction helpers
    # ------------------------------------------------------------------ #
    def _build_window(self) -> None:
        """Applies window flags: a normal titled window, or a stealth overlay."""
        if self._stealth:
            # Frameless, always-on-top, translucent; ``Tool`` keeps it out of the Dock.
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            # Keep the Tool window visible even when sufler is not the active macOS app.
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        else:
            # Normal window: native title bar (drag + close button), kept on top.
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("sufler")
        self.resize(400, 340)
        self._move_to_corner()

    def _move_to_corner(self) -> None:
        """Positions the overlay near the top-right of the primary screen."""
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.right() - self.width() - 20, area.top() + 40)

    @staticmethod
    def _capture_icon() -> QtGui.QIcon:
        """Draws a monochrome camera icon (font-independent, fits the dark UI).

        Returns:
            QtGui.QIcon: A crisp vector camera icon for the capture button.
        """
        size = 24
        pix = QtGui.QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pix)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        color = QtGui.QColor("#f2f2f2")
        painter.setPen(QtGui.QPen(color, 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Viewfinder bump on top of the body.
        painter.drawRoundedRect(QtCore.QRectF(8.0, 4.5, 8.0, 4.0), 1.5, 1.5)
        # Camera body.
        painter.drawRoundedRect(QtCore.QRectF(2.5, 7.5, 19.0, 13.0), 3.0, 3.0)
        # Lens: outer ring + filled centre.
        painter.drawEllipse(QtCore.QPointF(12.0, 14.5), 4.2, 4.2)
        painter.setBrush(color)
        painter.drawEllipse(QtCore.QPointF(12.0, 14.5), 1.6, 1.6)
        painter.end()
        return QtGui.QIcon(pix)

    def _build_widgets(self) -> None:
        """Creates the child widgets (labels, button, input)."""
        self._question_label = QtWidgets.QLabel("", self)
        self._question_label.setObjectName("questionLabel")
        self._question_label.setWordWrap(True)
        self._question_label.setTextFormat(Qt.TextFormat.PlainText)

        self._answer_label = QtWidgets.QLabel("", self)
        self._answer_label.setObjectName("answerLabel")
        self._answer_label.setWordWrap(True)
        self._answer_label.setTextFormat(Qt.TextFormat.PlainText)
        self._answer_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._answer_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._capture_button = QtWidgets.QPushButton(self)
        self._capture_button.setObjectName("captureButton")
        self._capture_button.setIcon(self._capture_icon())
        self._capture_button.setIconSize(QtCore.QSize(20, 20))
        self._capture_button.setToolTip("Скриншот экрана → Claude")
        self._capture_button.setCursor(Qt.CursorShape.PointingHandCursor)

        self._input_field = QtWidgets.QLineEdit(self)
        self._input_field.setObjectName("inputField")
        self._input_field.setPlaceholderText("Введите вопрос вручную…")
        self._input_field.setClearButtonEnabled(True)

        self._send_button = QtWidgets.QPushButton("⏎", self)
        self._send_button.setObjectName("sendButton")
        self._send_button.setToolTip("Отправить (Enter)")
        self._send_button.setCursor(Qt.CursorShape.PointingHandCursor)

        self._transcript = QtWidgets.QTextEdit(self)
        self._transcript.setObjectName("transcript")
        self._transcript.setReadOnly(True)
        self._transcript.setPlaceholderText("Распознанная речь появится здесь…")
        self._transcript.setMaximumHeight(120)

        self._transcript_toggle = QtWidgets.QCheckBox("Показывать распознавание", self)
        self._transcript_toggle.setObjectName("transcriptToggle")
        self._transcript_toggle.setChecked(True)

        self.setStyleSheet(self._stylesheet())

    def _build_layout(self) -> None:
        """Arranges the child widgets in a vertical layout."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        layout.addWidget(self._question_label)
        layout.addWidget(self._answer_label, stretch=1)
        layout.addWidget(self._transcript, stretch=1)

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(6)
        controls.addWidget(self._capture_button)
        controls.addWidget(self._input_field, stretch=1)
        controls.addWidget(self._send_button)
        layout.addLayout(controls)
        layout.addWidget(self._transcript_toggle)

    def _connect_signals(self) -> None:
        """Wires child-widget signals to the overlay's public signals."""
        self._capture_button.clicked.connect(self._on_capture_clicked)
        self._input_field.returnPressed.connect(self._on_input_submitted)
        self._send_button.clicked.connect(self._on_input_submitted)
        self._transcript_toggle.toggled.connect(self.set_transcript_visible)

    @staticmethod
    def _stylesheet() -> str:
        """Returns the Qt style sheet for the overlay (rounded, dark, small font).

        Returns:
            str: The style sheet applied to the overlay and its children.
        """
        return """
            QWidget {
                background-color: rgba(20, 20, 24, 235);
                color: #f2f2f2;
                font-family: -apple-system, "SF Pro Text", "Helvetica Neue", sans-serif;
                border-radius: 10px;
            }
            QLabel#questionLabel {
                color: #9ad1ff;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#answerLabel {
                color: #f2f2f2;
                font-size: 13px;
            }
            QPushButton#captureButton, QPushButton#sendButton {
                background-color: rgba(60, 60, 70, 230);
                border: 1px solid rgba(120, 120, 140, 200);
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 15px;
            }
            QPushButton#captureButton:hover, QPushButton#sendButton:hover {
                background-color: rgba(80, 80, 92, 240);
            }
            QLineEdit#inputField {
                background-color: rgba(40, 40, 48, 230);
                border: 1px solid rgba(110, 110, 130, 200);
                border-radius: 6px;
                padding: 4px 6px;
                font-size: 12px;
            }
            QTextEdit#transcript {
                background-color: rgba(30, 34, 40, 230);
                border: 1px solid rgba(90, 110, 130, 180);
                border-radius: 6px;
                color: #cfe8ff;
                font-size: 12px;
            }
            QCheckBox#transcriptToggle {
                color: #b8b8c0;
                font-size: 11px;
            }
        """

    # ------------------------------------------------------------------ #
    # Internal slots
    # ------------------------------------------------------------------ #
    def _on_capture_clicked(self) -> None:
        """Re-emits the capture button click as :pyattr:`capture_requested`."""
        logger.debug("Capture requested via button")
        self.capture_requested.emit()

    def _on_input_submitted(self) -> None:
        """Emits :pyattr:`text_submitted` with the trimmed input and clears it."""
        text = self._input_field.text().strip()
        if not text:
            return
        logger.debug("Manual text submitted (%d chars)", len(text))
        self._input_field.clear()
        self.text_submitted.emit(text)

    # ------------------------------------------------------------------ #
    # Content API
    # ------------------------------------------------------------------ #
    def set_question(self, text: str) -> None:
        """Sets the recognized question shown in the top area.

        Args:
            text (str): The recognized question text to display.
        """
        self._question_label.setText(text)

    def question_text(self) -> str:
        """Returns the currently displayed question text.

        Returns:
            str: The text shown in the question area.
        """
        return self._question_label.text()

    def begin_answer(self) -> None:
        """Clears the answer area in preparation for a new streamed answer."""
        self._answer_label.clear()

    def append_answer(self, token: str) -> None:
        """Appends a single streamed token to the answer area.

        Args:
            token (str): The next token (or chunk) of the answer to append.
        """
        self._answer_label.setText(self._answer_label.text() + token)

    def answer_text(self) -> str:
        """Returns the full answer accumulated so far.

        Returns:
            str: The text shown in the answer area.
        """
        return self._answer_label.text()

    # ------------------------------------------------------------------ #
    # Live transcript (recognized speech feed)
    # ------------------------------------------------------------------ #
    def append_transcript(self, text: str) -> None:
        """Appends a finalized recognized utterance to the live transcript.

        Args:
            text (str): The recognized text to append (blank text is ignored).
        """
        text = text.strip()
        if text:
            self._transcript.append(text)  # new paragraph + auto-scroll

    def clear_transcript(self) -> None:
        """Clears the live transcript area."""
        self._transcript.clear()

    def set_transcript_visible(self, visible: bool) -> None:
        """Shows or hides the live transcript (the recognition feed)."""
        self._transcript.setVisible(visible)
        if self._transcript_toggle.isChecked() != visible:
            self._transcript_toggle.setChecked(visible)

    def is_transcript_visible(self) -> bool:
        """Returns whether the live transcript is currently visible.

        Returns:
            bool: ``True`` if the transcript area is visible.
        """
        return self._transcript.isVisible()

    # ------------------------------------------------------------------ #
    # Stealth controls
    # ------------------------------------------------------------------ #
    def set_mode(self, mode: Mode) -> None:
        """Applies a suggestion :class:`~src.models.enums.Mode` to the overlay.

        ``Mode.COACH`` shows only minimal support, so the question area is
        hidden (compact). ``Mode.ANSWER`` shows the full ready answer with the
        question visible.

        Args:
            mode (Mode): The suggestion mode to apply.
        """
        self.set_compact(mode is Mode.COACH)
        logger.debug("Mode set to %s", mode.value)

    def cycle_opacity(self) -> None:
        """Cycles window opacity through 20 % -> 40 % -> 70 % -> 20 %."""
        self._opacity_index = (self._opacity_index + 1) % len(OPACITY_LEVELS)
        self.set_opacity_percent(OPACITY_LEVELS[self._opacity_index])

    def set_opacity_percent(self, pct: int) -> None:
        """Sets the window opacity from a percentage value.

        The value is clamped to the inclusive ``[5, 100]`` range so the overlay
        never becomes fully invisible (use :meth:`panic_hide` for that).

        Args:
            pct (int): Desired opacity in percent.
        """
        clamped = max(5, min(100, pct))
        self.setWindowOpacity(clamped / 100.0)
        logger.debug("Opacity set to %d%%", clamped)

    def opacity_percent(self) -> int:
        """Returns the current window opacity as a rounded percentage.

        Returns:
            int: The window opacity in percent.
        """
        return round(self.windowOpacity() * 100)

    def toggle_click_through(self) -> None:
        """Toggles click-through mode (mouse events pass through the overlay)."""
        self.set_click_through(not self._click_through)

    def set_click_through(self, enabled: bool) -> None:
        """Enables or disables click-through mode.

        When enabled, ``WA_TransparentForMouseEvents`` makes every click pass
        through to the window beneath the overlay.

        Args:
            enabled (bool): ``True`` to let clicks pass through.
        """
        self._click_through = enabled
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        logger.debug("Click-through %s", "enabled" if enabled else "disabled")

    def is_click_through(self) -> bool:
        """Returns whether click-through mode is currently enabled.

        Returns:
            bool: ``True`` if clicks pass through the overlay.
        """
        return self._click_through

    def toggle_compact(self) -> None:
        """Toggles compact mode (hide the question area, answer only)."""
        self.set_compact(not self._compact)

    def set_compact(self, enabled: bool) -> None:
        """Enables or disables compact mode.

        In compact mode the question area is hidden and only the streamed
        answer remains visible.

        Args:
            enabled (bool): ``True`` to hide the question area.
        """
        self._compact = enabled
        self._question_label.setVisible(not enabled)
        logger.debug("Compact mode %s", "enabled" if enabled else "disabled")

    def is_compact(self) -> bool:
        """Returns whether compact mode is currently enabled.

        Returns:
            bool: ``True`` if the question area is hidden.
        """
        return self._compact

    def panic_hide(self) -> None:
        """Instantly hides the entire overlay (panic control)."""
        self._auto_hide_timer.stop()
        self.hide()
        logger.debug("Panic hide triggered")

    def arm_auto_hide(self, seconds: float = DEFAULT_AUTO_HIDE_SECONDS) -> None:
        """Schedules the overlay to hide itself after a delay.

        Any previously armed auto-hide is cancelled and replaced.

        Args:
            seconds (float): Delay before hiding. Non-positive values cancel a
                pending auto-hide instead of scheduling one.
        """
        if seconds <= 0:
            self._auto_hide_timer.stop()
            logger.debug("Auto-hide cancelled")
            return
        self._auto_hide_timer.start(int(seconds * 1000))
        logger.debug("Auto-hide armed for %.1fs", seconds)

    # ------------------------------------------------------------------ #
    # Qt event overrides
    # ------------------------------------------------------------------ #
    # Drag the window by its body (works for the frameless stealth mode too).
    def mousePressEvent(self, event: QtGui.QMouseEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Begins a window drag on left-button press."""
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Moves the window while the left button is held."""
        if event is not None and self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Ends a window drag."""
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    # ``keyPressEvent`` is a Qt-mandated camelCase override name.
    def keyPressEvent(self, event: QtGui.QKeyEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Adds a local Escape panic shortcut on top of global hotkeys.

        Args:
            event (QtGui.QKeyEvent | None): The incoming key event.
        """
        if event is not None and event.key() == Qt.Key.Key_Escape:
            self.panic_hide()
            event.accept()
            return
        super().keyPressEvent(event)


class _MockAnswerStreamer(QtCore.QObject):
    """Streams :data:`MOCK_ANSWER_TOKENS` into an overlay via a QTimer.

    This is a Phase-1 stand-in for the real LLM stream; it appends one token
    per timer tick to prove the overlay's streaming API works end to end.
    """

    def __init__(self, overlay: Overlay, interval_ms: int = 120) -> None:
        """Creates a streamer bound to an overlay.

        Args:
            overlay (Overlay): The overlay to stream tokens into.
            interval_ms (int): Delay between tokens, in milliseconds.
        """
        super().__init__(overlay)
        self._overlay = overlay
        self._index = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._emit_next_token)

    def start(self) -> None:
        """Resets the cursor and begins streaming the mocked answer."""
        self._index = 0
        self._overlay.begin_answer()
        self._timer.start()

    def _emit_next_token(self) -> None:
        """Appends the next mock token, stopping when the answer is complete."""
        if self._index >= len(MOCK_ANSWER_TOKENS):
            self._timer.stop()
            self._overlay.arm_auto_hide()
            return
        self._overlay.append_answer(MOCK_ANSWER_TOKENS[self._index])
        self._index += 1


def demo() -> None:
    """Runs a small interactive demo of the overlay (Phase 1, mocked answer).

    Shows the overlay near the top-right of the primary screen and, when the
    "📸 Скрин" button is pressed (or a manual question is submitted), streams a
    placeholder answer token-by-token via a :class:`~PyQt6.QtCore.QTimer`.
    """
    existing = QtWidgets.QApplication.instance()
    app: QtWidgets.QApplication = (
        existing if isinstance(existing, QtWidgets.QApplication) else QtWidgets.QApplication(sys.argv)
    )

    overlay = Overlay()
    streamer = _MockAnswerStreamer(overlay)

    def _stream_for_capture() -> None:
        overlay.set_question("Demo: what is the GIL in CPython?")
        streamer.start()

    def _stream_for_text(text: str) -> None:
        overlay.set_question(text)
        streamer.start()

    overlay.capture_requested.connect(_stream_for_capture)
    overlay.text_submitted.connect(_stream_for_text)

    # Position near the top-right corner of the primary screen.
    screen = QtWidgets.QApplication.primaryScreen()
    if screen is not None:
        geometry = screen.availableGeometry()
        overlay.move(geometry.right() - overlay.width() - 24, geometry.top() + 60)

    overlay.set_question("Press 📸 Скрин to stream a mocked answer.")
    overlay.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    demo()
