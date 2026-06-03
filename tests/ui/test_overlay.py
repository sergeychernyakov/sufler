# tests/ui/test_overlay.py

"""Tests for :mod:`src.ui.overlay` (PyQt6 stealth overlay, Phase 1).

The suite drives the public ``Overlay`` API with pytest-qt's ``qtbot`` under the
offscreen Qt platform (configured in ``conftest.py``). Each test follows the
Arrange -> Act -> Assert pattern.
"""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from src.models.enums import Mode
from src.ui.overlay import (
    DEFAULT_AUTO_HIDE_SECONDS,
    MOCK_ANSWER_TOKENS,
    OPACITY_LEVELS,
    Overlay,
    _LevelMeter,
    _MockAnswerStreamer,
    demo,
)


def test_initial_state(overlay: Overlay) -> None:
    """A fresh overlay starts at the highest opacity with no click-through."""
    # Assert
    assert overlay.opacity_percent() == OPACITY_LEVELS[-1]
    assert overlay.is_click_through() is False
    assert overlay.is_compact() is False
    assert overlay.question_text() == ""
    assert overlay.answer_text() == ""


def test_set_question_updates_visible_text(overlay: Overlay) -> None:
    """``set_question`` updates the text shown in the question area."""
    # Act
    overlay.set_question("What is the GIL?")

    # Assert
    assert overlay.question_text() == "What is the GIL?"


def test_begin_answer_clears_previous_answer(overlay: Overlay) -> None:
    """``begin_answer`` clears any previously streamed answer."""
    # Arrange
    overlay.append_answer("stale text")

    # Act
    overlay.begin_answer()

    # Assert
    assert overlay.answer_text() == ""


def test_append_answer_accumulates_tokens(overlay: Overlay) -> None:
    """``append_answer`` concatenates streamed tokens in order."""
    # Arrange
    overlay.begin_answer()

    # Act
    for token in ("Hel", "lo, ", "world"):
        overlay.append_answer(token)

    # Assert
    assert overlay.answer_text() == "Hello, world"


def test_cycle_opacity_walks_levels(overlay: Overlay) -> None:
    """``cycle_opacity`` walks 70 -> 20 -> 40 -> 70 and updates windowOpacity."""
    # Arrange: starts at the last level (70 %).
    assert overlay.opacity_percent() == 70

    # Act / Assert: cycling wraps through the configured levels.
    overlay.cycle_opacity()
    assert overlay.opacity_percent() == 20
    assert overlay.windowOpacity() == pytest.approx(0.20, abs=0.01)

    overlay.cycle_opacity()
    assert overlay.opacity_percent() == 40

    overlay.cycle_opacity()
    assert overlay.opacity_percent() == 70


def test_set_opacity_percent_changes_window_opacity(overlay: Overlay) -> None:
    """``set_opacity_percent`` maps a percentage onto ``windowOpacity``."""
    # Act
    overlay.set_opacity_percent(50)

    # Assert: Qt quantizes windowOpacity to 8 bits, so allow ~1/255 slack.
    assert overlay.windowOpacity() == pytest.approx(0.50, abs=0.01)
    assert overlay.opacity_percent() == 50


@pytest.mark.parametrize(
    ("requested", "expected_pct"),
    [(0, 5), (-100, 5), (200, 100), (100, 100), (5, 5)],
)
def test_set_opacity_percent_clamps_out_of_range(overlay: Overlay, requested: int, expected_pct: int) -> None:
    """Opacity is clamped to the inclusive [5, 100] range (never invisible)."""
    # Act
    overlay.set_opacity_percent(requested)

    # Assert
    assert overlay.opacity_percent() == expected_pct


def test_toggle_compact_hides_question_area(overlay: Overlay, qtbot) -> None:
    """``toggle_compact`` hides the question area, leaving only the answer."""
    # Arrange
    overlay.show()
    qtbot.waitExposed(overlay)
    question_label = overlay.findChild(overlay._question_label.__class__, "questionLabel")
    assert question_label is not None
    assert question_label.isVisible() is True

    # Act
    overlay.toggle_compact()

    # Assert
    assert overlay.is_compact() is True
    assert question_label.isVisible() is False

    # Act: toggling back restores visibility.
    overlay.toggle_compact()
    assert overlay.is_compact() is False
    assert question_label.isVisible() is True


def test_set_mode_coach_is_compact_answer_is_full(overlay: Overlay) -> None:
    """``Mode.COACH`` enables compact mode; ``Mode.ANSWER`` disables it."""
    # Act
    overlay.set_mode(Mode.COACH)
    # Assert
    assert overlay.is_compact() is True

    # Act
    overlay.set_mode(Mode.ANSWER)
    # Assert
    assert overlay.is_compact() is False


def test_toggle_click_through_flips_attribute(overlay: Overlay) -> None:
    """``toggle_click_through`` flips ``WA_TransparentForMouseEvents``."""
    # Arrange
    attr = Qt.WidgetAttribute.WA_TransparentForMouseEvents
    assert overlay.testAttribute(attr) is False

    # Act
    overlay.toggle_click_through()

    # Assert
    assert overlay.is_click_through() is True
    assert overlay.testAttribute(attr) is True

    # Act: toggling again restores normal mouse handling.
    overlay.toggle_click_through()
    assert overlay.is_click_through() is False
    assert overlay.testAttribute(attr) is False


def test_panic_hide_makes_widget_hidden(overlay: Overlay, qtbot) -> None:
    """``panic_hide`` instantly hides the overlay and cancels auto-hide."""
    # Arrange
    overlay.show()
    qtbot.waitExposed(overlay)
    overlay.arm_auto_hide(5.0)
    assert overlay.isVisible() is True

    # Act
    overlay.panic_hide()

    # Assert
    assert overlay.isVisible() is False
    assert overlay._auto_hide_timer.isActive() is False


def test_escape_key_triggers_panic_hide(overlay: Overlay, qtbot) -> None:
    """Pressing Escape acts as a local panic hide."""
    # Arrange
    overlay.show()
    qtbot.waitExposed(overlay)

    # Act
    qtbot.keyClick(overlay, Qt.Key.Key_Escape)

    # Assert
    assert overlay.isVisible() is False


def test_arm_auto_hide_starts_single_shot_timer(overlay: Overlay) -> None:
    """``arm_auto_hide`` starts a single-shot timer with the given delay."""
    # Act
    overlay.arm_auto_hide(3.0)

    # Assert
    assert overlay._auto_hide_timer.isActive() is True
    assert overlay._auto_hide_timer.isSingleShot() is True
    assert overlay._auto_hide_timer.interval() == 3000


def test_arm_auto_hide_non_positive_cancels(overlay: Overlay) -> None:
    """A non-positive delay cancels any pending auto-hide instead of arming."""
    # Arrange
    overlay.arm_auto_hide(5.0)
    assert overlay._auto_hide_timer.isActive() is True

    # Act
    overlay.arm_auto_hide(0)

    # Assert
    assert overlay._auto_hide_timer.isActive() is False


def test_arm_auto_hide_hides_after_timeout(overlay: Overlay, qtbot) -> None:
    """An armed auto-hide eventually hides the overlay when the timer fires."""
    # Arrange
    overlay.show()
    qtbot.waitExposed(overlay)

    # Act
    overlay.arm_auto_hide(0.05)

    # Assert: the overlay becomes hidden once the timer elapses.
    qtbot.waitUntil(lambda: not overlay.isVisible(), timeout=2000)
    assert overlay.isVisible() is False


def test_arm_auto_hide_default_seconds(overlay: Overlay) -> None:
    """Calling ``arm_auto_hide`` without arguments uses the spec default."""
    # Act
    overlay.arm_auto_hide()

    # Assert
    assert overlay._auto_hide_timer.interval() == int(DEFAULT_AUTO_HIDE_SECONDS * 1000)


def test_capture_button_emits_capture_requested(overlay: Overlay, qtbot) -> None:
    """Clicking the capture button emits ``capture_requested``."""
    # Arrange
    button = overlay.findChild(overlay._capture_button.__class__, "captureButton")
    assert button is not None

    # Act / Assert
    with qtbot.waitSignal(overlay.capture_requested, timeout=1000):
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def test_text_submitted_emits_on_enter(overlay: Overlay, qtbot) -> None:
    """Typing text and pressing Enter emits ``text_submitted`` with the text."""
    # Arrange
    field = overlay._input_field
    field.setText("manual question")

    # Act / Assert
    with qtbot.waitSignal(overlay.text_submitted, timeout=1000) as blocker:
        qtbot.keyClick(field, Qt.Key.Key_Return)
    assert blocker.args == ["manual question"]
    # The field is cleared after a successful submit.
    assert field.text() == ""


def test_text_submitted_trims_whitespace(overlay: Overlay, qtbot) -> None:
    """Submitted text is stripped of surrounding whitespace."""
    # Arrange
    overlay._input_field.setText("   spaced out   ")

    # Act / Assert
    with qtbot.waitSignal(overlay.text_submitted, timeout=1000) as blocker:
        qtbot.keyClick(overlay._input_field, Qt.Key.Key_Return)
    assert blocker.args == ["spaced out"]


def test_empty_input_does_not_emit(overlay: Overlay, qtbot) -> None:
    """Pressing Enter on blank/whitespace-only input emits nothing."""
    # Arrange
    overlay._input_field.setText("    ")

    # Act / Assert
    with qtbot.assertNotEmitted(overlay.text_submitted):
        qtbot.keyClick(overlay._input_field, Qt.Key.Key_Return)


def test_mock_streamer_streams_full_answer(overlay: Overlay, qtbot) -> None:
    """The mock streamer appends every token and arms auto-hide when done."""
    # Arrange
    overlay.append_answer("leftover")
    streamer = _MockAnswerStreamer(overlay, interval_ms=1)

    # Act
    streamer.start()
    # begin_answer is called by start(), clearing the leftover text.
    assert overlay.answer_text() == ""
    expected = "".join(MOCK_ANSWER_TOKENS)
    qtbot.waitUntil(lambda: overlay.answer_text() == expected, timeout=3000)

    # Assert
    assert overlay.answer_text() == expected
    assert overlay._auto_hide_timer.isActive() is True


def test_demo_builds_and_shows_overlay(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    """``demo`` wires an overlay and streamer without entering the event loop."""
    # Arrange: stop demo before it blocks on app.exec()/sys.exit().
    created: dict[str, Overlay] = {}
    original_show = Overlay.show

    def _capture_show(self: Overlay) -> None:
        created["overlay"] = self
        qtbot.addWidget(self)
        original_show(self)
        raise KeyboardInterrupt  # unwind out of demo() before sys.exit

    monkeypatch.setattr(Overlay, "show", _capture_show)
    monkeypatch.setattr("src.ui.overlay.sys.exit", lambda *_: None)

    # Act
    with pytest.raises(KeyboardInterrupt):
        demo()

    # Assert: an overlay was created, shown and given an initial prompt.
    assert isinstance(created.get("overlay"), Overlay)
    assert created["overlay"].question_text() != ""
    assert QApplication.instance() is not None


# --------------------------------------------------------------------------- #
# Microphone toggle
# --------------------------------------------------------------------------- #
def test_mic_button_defaults_to_listening(overlay: Overlay) -> None:
    """The mic toggle starts in the listening (on) state."""
    # Assert
    assert overlay.is_listening() is True


def test_mic_click_toggles_state_and_emits(overlay: Overlay, qtbot) -> None:
    """Clicking the mic mutes it and emits ``mic_toggled(False)``, then back on."""
    # Act / Assert: first click turns listening off.
    with qtbot.waitSignal(overlay.mic_toggled, timeout=1000) as blocker:
        qtbot.mouseClick(overlay._mic_button, Qt.MouseButton.LeftButton)
    assert blocker.args == [False]
    assert overlay.is_listening() is False

    # Act / Assert: a second click turns it back on.
    with qtbot.waitSignal(overlay.mic_toggled, timeout=1000) as blocker:
        qtbot.mouseClick(overlay._mic_button, Qt.MouseButton.LeftButton)
    assert blocker.args == [True]
    assert overlay.is_listening() is True


def test_set_listening_updates_state_without_emitting(overlay: Overlay, qtbot) -> None:
    """``set_listening`` syncs the button without emitting ``mic_toggled``."""
    # Act / Assert
    with qtbot.assertNotEmitted(overlay.mic_toggled):
        overlay.set_listening(False)
    assert overlay.is_listening() is False

    overlay.set_listening(True)
    assert overlay.is_listening() is True


def test_set_mic_enabled_false_disables_and_mutes(overlay: Overlay) -> None:
    """Disabling the mic (STT unavailable) mutes it and disables the button."""
    # Act
    overlay.set_mic_enabled(False)

    # Assert
    assert overlay.is_listening() is False
    assert overlay._mic_button.isEnabled() is False

    # Act: re-enabling restores an interactive button.
    overlay.set_mic_enabled(True)
    assert overlay._mic_button.isEnabled() is True


# --------------------------------------------------------------------------- #
# Brand title
# --------------------------------------------------------------------------- #
def test_window_title_is_capitalized(overlay: Overlay) -> None:
    """The window title uses the capitalized brand name."""
    # Assert
    assert overlay.windowTitle() == "Sufler"


def test_header_shows_capitalized_left_aligned_brand(overlay: Overlay) -> None:
    """The in-window header shows 'Sufler' (capitalized) and is left-aligned."""
    # Assert
    assert overlay._header_label.text() == "Sufler"
    assert bool(overlay._header_label.alignment() & Qt.AlignmentFlag.AlignLeft)


# --------------------------------------------------------------------------- #
# Microphone input volume + level meter
# --------------------------------------------------------------------------- #
def test_volume_slider_emits_input_volume_changed(overlay: Overlay, qtbot) -> None:
    """Moving the volume slider emits ``input_volume_changed`` with the new value."""
    # Act / Assert
    with qtbot.waitSignal(overlay.input_volume_changed, timeout=1000) as blocker:
        overlay._volume_slider.setValue(33)
    assert blocker.args == [33]
    assert overlay.input_volume() == 33


def test_set_input_volume_does_not_emit(overlay: Overlay, qtbot) -> None:
    """``set_input_volume`` syncs the slider without emitting ``input_volume_changed``."""
    # Act / Assert
    with qtbot.assertNotEmitted(overlay.input_volume_changed):
        overlay.set_input_volume(70)
    assert overlay.input_volume() == 70


def test_set_input_level_updates_and_clamps_meter(overlay: Overlay) -> None:
    """``set_input_level`` updates the meter and clamps the value to [0, 1]."""
    # Act / Assert
    overlay.set_input_level(0.5)
    assert overlay._level_meter._level == pytest.approx(0.5)
    overlay.set_input_level(2.0)
    assert overlay._level_meter._level == 1.0


def test_level_meter_paints_without_error(qtbot) -> None:
    """The level meter renders (exercising its paint branches) without raising."""
    # Arrange
    meter = _LevelMeter()
    qtbot.addWidget(meter)

    # Act / Assert: grab() forces a paintEvent over green/amber/red bars.
    meter.set_level(0.9)
    meter.grab()
