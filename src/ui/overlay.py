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

import html
import re
import sys
from typing import Final
from urllib.parse import quote, unquote

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

# Font zoom (Cmd +/-/0): a multiplier applied to every stylesheet font-size.
FONT_SCALE_STEP: Final[float] = 0.1
FONT_SCALE_MIN: Final[float] = 0.7
FONT_SCALE_MAX: Final[float] = 2.5

# Braille spinner frames for the "thinking" indicator shown before the first answer token.
_SPINNER_FRAMES: Final[str] = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

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


class _LevelMeter(QtWidgets.QWidget):
    """Horizontal VU-style meter: a row of bars lit in proportion to the input level.

    The level is the peak amplitude (0..1) of the most recent microphone block; a
    perceptual square-root curve maps it to lit bars so ordinary speech fills a
    useful range, and the top bars turn amber/red to warn of clipping.
    """

    _BARS: Final[int] = 12

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        """Builds an empty (zero-level) meter."""
        super().__init__(parent)
        self._level: float = 0.0
        self.setMinimumWidth(120)
        self.setFixedHeight(14)

    def set_level(self, level: float) -> None:
        """Sets the displayed level (clamped to ``0..1``) and repaints.

        Args:
            level (float): Peak amplitude in ``[0, 1]``.
        """
        self._level = max(0.0, min(1.0, level))
        self.update()

    # ``paintEvent`` is a Qt-mandated camelCase override name.
    def paintEvent(  # noqa: N802  # pylint: disable=invalid-name,unused-argument
        self, event: QtGui.QPaintEvent | None
    ) -> None:
        """Paints the bars: green, then amber, then red towards the top."""
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            painter.setOpacity(0.4)  # fade the whole meter when the mic is off
        width = float(self.width())
        height = float(self.height())
        gap = 2.0
        bar_w = max(1.0, (width - gap * (self._BARS - 1)) / self._BARS)
        lit = int(round((self._level**0.5) * self._BARS))
        for i in range(self._BARS):
            frac = i / (self._BARS - 1)
            if i >= lit:
                color = QtGui.QColor(255, 255, 255, 38)
            elif frac > 0.85:
                color = QtGui.QColor("#ff5b5b")
            elif frac > 0.7:
                color = QtGui.QColor("#ffcf5b")
            else:
                color = QtGui.QColor("#5ed16a")
            painter.fillRect(QtCore.QRectF(i * (bar_w + gap), 2.0, bar_w, height - 4.0), color)
        painter.end()


class Overlay(QtWidgets.QWidget):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Frameless, always-on-top stealth overlay widget.

    The widget renders two stacked text areas (question and answer), a capture
    button and a permanent manual-input field. It is meant to be driven by an
    external controller via :pyattr:`capture_requested` / :pyattr:`text_submitted`
    and the public setter/streaming methods.

    Signals:
        capture_requested: Emitted when the capture (camera) button is pressed.
        text_submitted (str): Emitted with the (non-empty) manual input text
            when the user presses Enter in the input field.
        mic_toggled (bool): Emitted when the user toggles the microphone button —
            ``True`` to start listening, ``False`` to mute.
        input_volume_changed (int): Emitted when the user moves the microphone
            volume slider (0..100).
    """

    capture_requested = pyqtSignal()
    text_submitted = pyqtSignal(str)
    mic_toggled = pyqtSignal(bool)
    input_volume_changed = pyqtSignal(int)
    term_activated = pyqtSignal(str)
    back_requested = pyqtSignal()

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
        self._font_scale: float = 1.0

        # Single-shot timer used by ``arm_auto_hide``.
        self._auto_hide_timer = QtCore.QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.panic_hide)

        # "Thinking" spinner shown in the answer area until the first LLM token arrives.
        self._got_answer_token: bool = False
        self._answer_raw: str = ""
        self._thinking_frame: int = 0
        self._thinking_timer = QtCore.QTimer(self)
        self._thinking_timer.timeout.connect(self._on_thinking_tick)

        self._build_window()
        self._build_widgets()
        self._build_layout()
        self._connect_signals()
        self._build_shortcuts()

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
        self.setWindowTitle("")
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
        pen = QtGui.QPen(color, 1.6)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Lens-housing hump on top (trapezoid) — sits above the lens, off to the left.
        hump = QtGui.QPolygonF(
            [
                QtCore.QPointF(8.0, 7.5),
                QtCore.QPointF(9.8, 4.8),
                QtCore.QPointF(14.2, 4.8),
                QtCore.QPointF(16.0, 7.5),
            ]
        )
        painter.drawPolygon(hump)
        # Camera body.
        painter.drawRoundedRect(QtCore.QRectF(2.5, 7.5, 19.0, 12.5), 2.8, 2.8)
        # Lens: two concentric rings (reads as a camera, not a latch).
        painter.drawEllipse(QtCore.QPointF(12.0, 14.0), 4.3, 4.3)
        painter.drawEllipse(QtCore.QPointF(12.0, 14.0), 2.0, 2.0)
        # Flash: a small filled dot at the top-right of the body.
        painter.setBrush(color)
        painter.drawEllipse(QtCore.QPointF(18.0, 10.2), 0.85, 0.85)
        painter.end()
        return QtGui.QIcon(pix)

    @staticmethod
    def _mic_icon(active: bool) -> QtGui.QIcon:
        """Draws a microphone icon, visibly distinct for the on/off states.

        Args:
            active (bool): ``True`` draws a filled green "listening" microphone;
                ``False`` draws a dimmed, outlined microphone with a diagonal
                "muted" slash.

        Returns:
            QtGui.QIcon: A crisp vector microphone icon for the mic toggle button.
        """
        size = 24
        pix = QtGui.QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pix)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        color = QtGui.QColor("#5ed16a" if active else "#8a8a90")
        pen = QtGui.QPen(color, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        # Mic capsule (head): filled when listening, hollow when muted.
        if active:
            painter.setBrush(color)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QtCore.QRectF(9.0, 3.0, 6.0, 11.0), 3.0, 3.0)
        # Cradle (the U the capsule sits in) + stand + base.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QtCore.QRectF(6.0, 5.5, 12.0, 12.0), 180 * 16, 180 * 16)
        painter.drawLine(QtCore.QPointF(12.0, 17.5), QtCore.QPointF(12.0, 20.5))
        painter.drawLine(QtCore.QPointF(8.5, 20.5), QtCore.QPointF(15.5, 20.5))
        if not active:
            # Diagonal slash marks the muted state.
            painter.drawLine(QtCore.QPointF(5.0, 4.5), QtCore.QPointF(19.0, 19.5))
        painter.end()
        return QtGui.QIcon(pix)

    def _build_widgets(self) -> None:
        """Creates the child widgets (labels, button, input)."""
        self._question_label = QtWidgets.QLabel("", self)
        self._question_label.setObjectName("questionLabel")
        self._question_label.setWordWrap(True)
        self._question_label.setTextFormat(Qt.TextFormat.PlainText)
        self._question_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._answer_label = QtWidgets.QLabel("", self)
        self._answer_label.setObjectName("answerLabel")
        self._answer_label.setWordWrap(True)
        self._answer_label.setTextFormat(Qt.TextFormat.PlainText)
        self._answer_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._answer_label.setOpenExternalLinks(False)
        self._answer_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._back_button = QtWidgets.QPushButton("←", self)
        self._back_button.setObjectName("backButton")
        self._back_button.setToolTip("Назад к предыдущему ответу")
        self._back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_button.hide()

        self._capture_button = QtWidgets.QPushButton(self)
        self._capture_button.setObjectName("captureButton")
        self._capture_button.setIcon(self._capture_icon())
        self._capture_button.setIconSize(QtCore.QSize(20, 20))
        self._capture_button.setToolTip("Скриншот экрана → Claude")
        self._capture_button.setCursor(Qt.CursorShape.PointingHandCursor)

        # Microphone toggle: listening (on) by default; icon differs per state.
        self._mic_button = QtWidgets.QPushButton(self)
        self._mic_button.setObjectName("micButton")
        self._mic_button.setCheckable(True)
        self._mic_button.setChecked(True)
        self._mic_button.setIconSize(QtCore.QSize(20, 20))
        self._mic_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_mic_visuals()

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

        # Microphone input-volume slider + live level meter (no trip to System Settings).
        self._volume_label = QtWidgets.QLabel("Громкость", self)
        self._volume_label.setObjectName("controlLabel")
        self._volume_slider = QtWidgets.QSlider(Qt.Orientation.Horizontal, self)
        self._volume_slider.setObjectName("volumeSlider")
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(50)
        self._volume_slider.setToolTip("Громкость микрофона (системная)")
        self._volume_slider.setCursor(Qt.CursorShape.PointingHandCursor)

        self._level_label = QtWidgets.QLabel("Уровень", self)
        self._level_label.setObjectName("controlLabel")
        self._level_meter = _LevelMeter(self)

        self.setStyleSheet(self._scaled_stylesheet())

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
        controls.addWidget(self._back_button)
        controls.addWidget(self._capture_button)
        controls.addWidget(self._mic_button)
        controls.addWidget(self._input_field, stretch=1)
        controls.addWidget(self._send_button)
        layout.addLayout(controls)

        volume_row = QtWidgets.QHBoxLayout()
        volume_row.setSpacing(6)
        volume_row.addWidget(self._volume_label)
        volume_row.addWidget(self._volume_slider, stretch=1)
        layout.addLayout(volume_row)

        level_row = QtWidgets.QHBoxLayout()
        level_row.setSpacing(6)
        level_row.addWidget(self._level_label)
        level_row.addWidget(self._level_meter, stretch=1)
        layout.addLayout(level_row)

        layout.addWidget(self._transcript_toggle)

    def _connect_signals(self) -> None:
        """Wires child-widget signals to the overlay's public signals."""
        self._back_button.clicked.connect(self.back_requested)
        self._answer_label.linkActivated.connect(self._on_answer_link)
        self._capture_button.clicked.connect(self._on_capture_clicked)
        self._mic_button.clicked.connect(self._on_mic_clicked)
        self._input_field.returnPressed.connect(self._on_input_submitted)
        self._send_button.clicked.connect(self._on_input_submitted)
        self._transcript_toggle.toggled.connect(self.set_transcript_visible)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)

    def _build_shortcuts(self) -> None:
        """Wires keyboard shortcuts for font zoom (``Cmd +`` / ``Cmd -`` / ``Cmd 0`` on macOS)."""
        bindings = (
            (QtGui.QKeySequence.StandardKey.ZoomIn, self.increase_font),
            (QtGui.QKeySequence("Ctrl+="), self.increase_font),  # Cmd+= (no Shift) on macOS
            (QtGui.QKeySequence.StandardKey.ZoomOut, self.decrease_font),
            (QtGui.QKeySequence("Ctrl+-"), self.decrease_font),
            (QtGui.QKeySequence("Ctrl+0"), self.reset_font),
        )
        for sequence, slot in bindings:
            QtGui.QShortcut(sequence, self).activated.connect(slot)

    # ------------------------------------------------------------------ #
    # Font zoom (Cmd +/-/0)
    # ------------------------------------------------------------------ #
    def increase_font(self) -> None:
        """Increases the overlay font size by one step (``Cmd +``)."""
        self._set_font_scale(self._font_scale + FONT_SCALE_STEP)

    def decrease_font(self) -> None:
        """Decreases the overlay font size by one step (``Cmd -``)."""
        self._set_font_scale(self._font_scale - FONT_SCALE_STEP)

    def reset_font(self) -> None:
        """Resets the overlay font size to the default (``Cmd 0``)."""
        self._set_font_scale(1.0)

    def font_scale(self) -> float:
        """Returns the current font-zoom multiplier (1.0 = default).

        Returns:
            float: The font scale currently applied.
        """
        return self._font_scale

    def _set_font_scale(self, scale: float) -> None:
        """Clamps the font-zoom multiplier to ``[MIN, MAX]`` and restyles the overlay."""
        self._font_scale = max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, round(scale, 2)))
        self.setStyleSheet(self._scaled_stylesheet())
        logger.debug("Font scale -> %.2f", self._font_scale)

    def _scaled_stylesheet(self) -> str:
        """Returns the base style sheet with every font size scaled by the current zoom.

        Returns:
            str: The style sheet with each ``font-size`` multiplied by
            :pyattr:`_font_scale` (floored at 8 px).
        """

        def _scale(match: re.Match[str]) -> str:
            size = max(8, round(int(match.group(1)) * self._font_scale))
            return f"font-size: {size}px"

        return re.sub(r"font-size:\s*(\d+)px", _scale, self._stylesheet())

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
            QPushButton#captureButton, QPushButton#sendButton, QPushButton#micButton, QPushButton#backButton {
                background-color: rgba(60, 60, 70, 230);
                border: 1px solid rgba(120, 120, 140, 200);
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 15px;
            }
            QPushButton#captureButton:hover, QPushButton#sendButton:hover,
            QPushButton#micButton:hover, QPushButton#backButton:hover {
                background-color: rgba(80, 80, 92, 240);
            }
            QPushButton#micButton:checked {
                background-color: rgba(36, 78, 44, 235);
                border-color: rgba(110, 200, 130, 200);
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
            QLabel#controlLabel {
                color: #b8b8c0;
                font-size: 11px;
                min-width: 64px;
            }
            QLabel#controlLabel:disabled {
                color: #5a5a62;
            }
            QSlider#volumeSlider::groove:horizontal {
                height: 4px;
                background: rgba(255, 255, 255, 40);
                border-radius: 2px;
            }
            QSlider#volumeSlider::sub-page:horizontal {
                background: #5ed16a;
                border-radius: 2px;
            }
            QSlider#volumeSlider::sub-page:horizontal:disabled {
                background: rgba(255, 255, 255, 30);
            }
            QSlider#volumeSlider::handle:horizontal {
                width: 12px;
                margin: -5px 0;
                border-radius: 6px;
                background: #f2f2f2;
            }
            QSlider#volumeSlider::handle:horizontal:disabled {
                background: #6a6a72;
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

    def _on_mic_clicked(self, listening: bool) -> None:
        """Updates the mic icon/tooltip and re-emits the toggle as :pyattr:`mic_toggled`.

        Args:
            listening (bool): The button's new checked state (``True`` = listening).
        """
        self._update_mic_visuals()
        self._sync_input_controls()
        logger.debug("Microphone %s by user", "enabled" if listening else "disabled")
        self.mic_toggled.emit(listening)

    def _update_mic_visuals(self) -> None:
        """Syncs the mic button icon and tooltip to its checked (listening) state."""
        listening = self._mic_button.isChecked()
        self._mic_button.setIcon(self._mic_icon(listening))
        self._mic_button.setToolTip(
            "Слушаю — нажмите, чтобы выключить микрофон" if listening else "Микрофон выключен — нажмите, чтобы слушать"
        )

    def _on_volume_changed(self, percent: int) -> None:
        """Re-emits a user slider change as :pyattr:`input_volume_changed`."""
        logger.debug("Input volume slider -> %d%%", percent)
        self.input_volume_changed.emit(percent)

    def _sync_input_controls(self) -> None:
        """Dims the mic input controls when not listening, and zeroes the level meter.

        Active = the mic toggle is both on and available. When inactive, the volume
        slider, its labels and the level meter are disabled (greyed via the
        ``:disabled`` style) and the meter is reset to zero.
        """
        active = self._mic_button.isChecked() and self._mic_button.isEnabled()
        self._volume_label.setEnabled(active)
        self._volume_slider.setEnabled(active)
        self._level_label.setEnabled(active)
        self._level_meter.setEnabled(active)
        if not active:
            self._level_meter.set_level(0.0)

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
        """Clears the answer area and starts the 'thinking' spinner (until the first token)."""
        self._answer_label.clear()
        self._got_answer_token = False
        self._answer_raw = ""
        self._thinking_frame = 0
        self._thinking_timer.start(110)

    def append_answer(self, token: str) -> None:
        """Appends a streamed token (plain text), replacing the spinner on the first one.

        Args:
            token (str): The next token (or chunk) of the answer to append.
        """
        if not self._got_answer_token:
            self._thinking_timer.stop()
            self._got_answer_token = True
            self._answer_raw = ""
        self._answer_raw += token
        self._answer_label.setTextFormat(Qt.TextFormat.PlainText)
        self._answer_label.setText(self._answer_raw)

    def end_answer(self) -> None:
        """Ends a streamed answer: stops the spinner and renders **terms** as clickable links."""
        self._thinking_timer.stop()
        if not self._got_answer_token:
            self._answer_label.setTextFormat(Qt.TextFormat.PlainText)
            self._answer_label.setText("(пустой ответ)")
            return
        self._render_answer(self._answer_raw)

    def show_answer(self, raw: str) -> None:
        """Displays a finished answer (e.g. when navigating back), with clickable terms.

        Args:
            raw (str): The raw answer markdown to render.
        """
        self._thinking_timer.stop()
        self._got_answer_token = True
        self._render_answer(raw)

    def answer_raw(self) -> str:
        """Returns the raw (markdown) text of the current answer.

        Returns:
            str: The accumulated answer markdown (with ``**term**`` markers).
        """
        return self._answer_raw

    def set_back_visible(self, visible: bool) -> None:
        """Shows or hides the navigation back ("←") button.

        Args:
            visible (bool): ``True`` to show the back button.
        """
        self._back_button.setVisible(visible)

    def _render_answer(self, raw: str) -> None:
        """Stores ``raw`` and renders it as rich text with clickable ``**term**`` links."""
        self._answer_raw = raw
        self._answer_label.setTextFormat(Qt.TextFormat.RichText)
        self._answer_label.setText(self._linkify(raw))

    @staticmethod
    def _linkify(raw: str) -> str:
        """Renders answer markdown to HTML, turning each ``**term**`` into a clickable link.

        Args:
            raw (str): The raw answer text.

        Returns:
            str: HTML where every ``**term**`` is an ``<a href="term:...">`` link, other
            text is HTML-escaped and newlines become ``<br>``.
        """
        out: list[str] = []
        last = 0
        for match in re.finditer(r"\*\*(.+?)\*\*", raw):
            out.append(html.escape(raw[last : match.start()]))
            term = match.group(1).strip()
            out.append(f'<a href="term:{quote(term)}" style="color:#9ad1ff;">{html.escape(term)}</a>')
            last = match.end()
        out.append(html.escape(raw[last:]))
        return "".join(out).replace("\n", "<br>")

    def _on_answer_link(self, href: str) -> None:
        """Emits :pyattr:`term_activated` when a ``**term**`` link in the answer is clicked."""
        if href.startswith("term:"):
            self.term_activated.emit(unquote(href[len("term:") :]))

    def _on_thinking_tick(self) -> None:
        """Advances the 'thinking' spinner shown before the first answer token arrives."""
        self._thinking_frame = (self._thinking_frame + 1) % len(_SPINNER_FRAMES)
        self._answer_label.setTextFormat(Qt.TextFormat.PlainText)
        self._answer_label.setText(f"{_SPINNER_FRAMES[self._thinking_frame]}  думаю…")

    def answer_text(self) -> str:
        """Returns the text currently shown in the answer area.

        Returns:
            str: The answer label's text (raw during streaming; HTML once rendered).
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
    # Microphone (listening) control
    # ------------------------------------------------------------------ #
    def set_listening(self, listening: bool) -> None:
        """Reflects the real capture state on the mic button (no signal emitted).

        Updates the button, icon and tooltip only — it does **not** emit
        :pyattr:`mic_toggled` — so it is safe for syncing the UI to the actual
        pipeline state (e.g. at startup).

        Args:
            listening (bool): ``True`` shows the listening icon; ``False`` the muted icon.
        """
        self._mic_button.setChecked(listening)
        self._update_mic_visuals()
        self._sync_input_controls()

    def is_listening(self) -> bool:
        """Returns whether the mic toggle is in the listening (on) state.

        Returns:
            bool: ``True`` when listening is enabled.
        """
        return self._mic_button.isChecked()

    def set_mic_enabled(self, enabled: bool) -> None:
        """Enables/disables the mic toggle (disable when speech capture is unavailable).

        A disabled toggle is forced to the muted state and explains why via its tooltip.

        Args:
            enabled (bool): ``True`` to let the user toggle listening on/off.
        """
        self._mic_button.setEnabled(enabled)
        if enabled:
            self._update_mic_visuals()
            self._sync_input_controls()
            return
        self._mic_button.setChecked(False)
        self._mic_button.setIcon(self._mic_icon(False))
        self._mic_button.setToolTip("Распознавание речи недоступно")
        self._sync_input_controls()

    # ------------------------------------------------------------------ #
    # Microphone input volume + live level
    # ------------------------------------------------------------------ #
    def set_input_volume(self, percent: int) -> None:
        """Sets the volume slider position without emitting ``input_volume_changed``.

        Args:
            percent (int): Volume in percent (0..100, clamped). Used to sync the slider
                to the current system input volume at startup.
        """
        self._volume_slider.blockSignals(True)
        self._volume_slider.setValue(max(0, min(100, percent)))
        self._volume_slider.blockSignals(False)

    def input_volume(self) -> int:
        """Returns the current volume-slider value.

        Returns:
            int: Slider position in percent (0..100).
        """
        return self._volume_slider.value()

    def set_input_level(self, level: float) -> None:
        """Updates the live microphone input-level meter.

        Args:
            level (float): Peak amplitude in ``[0, 1]`` (clamped by the meter).
        """
        self._level_meter.set_level(level)

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
        self._thinking_timer.stop()
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
