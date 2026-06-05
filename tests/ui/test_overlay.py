# tests/ui/test_overlay.py

"""Tests for :mod:`src.ui.overlay` (PyQt6 stealth overlay, Phase 1).

The suite drives the public ``Overlay`` API with pytest-qt's ``qtbot`` under the
offscreen Qt platform (configured in ``conftest.py``). Each test follows the
Arrange -> Act -> Assert pattern.
"""

import re

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from src.models.enums import Mode
from src.ui.overlay import (
    DEFAULT_AUTO_HIDE_SECONDS,
    FONT_SCALE_MAX,
    FONT_SCALE_MIN,
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


def test_begin_answer_starts_thinking_spinner(overlay: Overlay) -> None:
    """begin_answer starts the spinner timer; a tick shows a 'думаю' indicator."""
    # Act
    overlay.begin_answer()
    # Assert
    assert overlay._thinking_timer.isActive() is True
    overlay._on_thinking_tick()
    assert "думаю" in overlay.answer_text()


def test_first_token_replaces_thinking_spinner(overlay: Overlay) -> None:
    """The first token stops the spinner and clears its 'думаю' placeholder."""
    # Arrange
    overlay.begin_answer()
    overlay._on_thinking_tick()  # spinner visible

    # Act
    overlay.append_answer("Ответ")

    # Assert
    assert overlay._thinking_timer.isActive() is False
    assert overlay.answer_text() == "Ответ"


def test_end_answer_without_token_marks_empty(overlay: Overlay) -> None:
    """end_answer with no tokens stops the spinner and shows an empty-answer note."""
    # Arrange
    overlay.begin_answer()

    # Act
    overlay.end_answer()

    # Assert
    assert overlay._thinking_timer.isActive() is False
    assert overlay.answer_text() == "(пустой ответ)"


def test_end_answer_after_token_keeps_answer(overlay: Overlay) -> None:
    """end_answer after tokens leaves the streamed answer intact."""
    # Arrange
    overlay.begin_answer()
    overlay.append_answer("Готовый ответ")

    # Act
    overlay.end_answer()

    # Assert
    assert overlay.answer_text() == "Готовый ответ"


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
def test_window_has_no_title_text(overlay: Overlay) -> None:
    """The window shows no title text (macOS centers titles; the brand lives in the Dock)."""
    # Assert
    assert overlay.windowTitle() == ""


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
    meter.setEnabled(False)  # also exercises the dimmed-when-disabled paint path
    meter.grab()


def test_muting_dims_input_controls_and_zeroes_level(overlay: Overlay) -> None:
    """Muting the mic disables (greys) the input controls and zeroes the meter."""
    # Arrange: listening, with a non-zero level on the meter.
    overlay.set_listening(True)
    overlay.set_input_level(0.8)

    # Act
    overlay.set_listening(False)

    # Assert: controls dimmed and the level reset.
    assert overlay._volume_slider.isEnabled() is False
    assert overlay._level_meter.isEnabled() is False
    assert overlay._level_meter._level == 0.0

    # Act: unmuting re-activates the controls.
    overlay.set_listening(True)
    assert overlay._volume_slider.isEnabled() is True
    assert overlay._level_meter.isEnabled() is True


# --------------------------------------------------------------------------- #
# Font zoom (Cmd +/-/0)
# --------------------------------------------------------------------------- #
def _max_font_px(stylesheet: str) -> int:
    """Return the largest ``font-size`` (px) declared in a stylesheet."""
    return max(int(size) for size in re.findall(r"font-size:\s*(\d+)px", stylesheet))


def test_font_starts_at_default_scale(overlay: Overlay) -> None:
    """A fresh overlay is at font scale 1.0."""
    assert overlay.font_scale() == 1.0


def test_increase_font_grows_scale_and_applied_sizes(overlay: Overlay) -> None:
    """``increase_font`` raises the scale and the applied font sizes."""
    before = _max_font_px(overlay.styleSheet())
    overlay.increase_font()
    assert overlay.font_scale() > 1.0
    assert _max_font_px(overlay.styleSheet()) > before


def test_decrease_then_reset_font(overlay: Overlay) -> None:
    """``decrease_font`` lowers the scale; ``reset_font`` returns to 1.0."""
    overlay.decrease_font()
    assert overlay.font_scale() < 1.0
    overlay.reset_font()
    assert overlay.font_scale() == 1.0


def test_font_scale_is_clamped(overlay: Overlay) -> None:
    """The font scale stays within [FONT_SCALE_MIN, FONT_SCALE_MAX]."""
    for _ in range(40):
        overlay.increase_font()
    assert overlay.font_scale() == pytest.approx(FONT_SCALE_MAX)
    for _ in range(60):
        overlay.decrease_font()
    assert overlay.font_scale() == pytest.approx(FONT_SCALE_MIN)


# --------------------------------------------------------------------------- #
# Selectable (copyable) text
# --------------------------------------------------------------------------- #
def test_question_and_answer_text_are_selectable(overlay: Overlay) -> None:
    """The question and answer areas allow mouse text selection (so they can be copied)."""
    flag = Qt.TextInteractionFlag.TextSelectableByMouse
    assert bool(overlay._question_label.textInteractionFlags() & flag)
    assert bool(overlay._answer_label.textInteractionFlags() & flag)


# --------------------------------------------------------------------------- #
# Clickable terms + back navigation
# --------------------------------------------------------------------------- #
def test_linkify_turns_bold_terms_into_links() -> None:
    """``**term**`` becomes an ``<a href="term:...">`` link; other text is preserved."""
    out = Overlay._linkify("1. **Фреймворк**: текст")
    assert '<a href="term:' in out
    assert "Фреймворк" in out
    assert "текст" in out


def test_linkify_turns_code_spans_into_links() -> None:
    """Backtick `code` terms (the English terms) also become clickable links."""
    out = Overlay._linkify("используй `thread` и `REST`")
    assert out.count('<a href="term:') == 2
    assert "thread" in out
    assert "REST" in out


def test_answer_link_click_emits_decoded_term(overlay: Overlay, qtbot) -> None:
    """Clicking a term link emits ``term_activated`` with the URL-decoded term."""
    with qtbot.waitSignal(overlay.term_activated, timeout=1000) as blocker:
        overlay._on_answer_link("term:Active%20Record")
    assert blocker.args == ["Active Record"]


def test_show_answer_sets_raw_and_back_button_toggles(overlay: Overlay) -> None:
    """show_answer stores the raw text; the back button is hidden by default and toggles."""
    assert overlay._back_button.isHidden() is True
    overlay.show_answer("**X**: y")
    assert overlay.answer_raw() == "**X**: y"

    overlay.set_back_visible(True)
    assert overlay._back_button.isHidden() is False
    overlay.set_back_visible(False)
    assert overlay._back_button.isHidden() is True


def test_back_button_emits_back_requested(overlay: Overlay, qtbot) -> None:
    """Activating the back button emits ``back_requested``."""
    with qtbot.waitSignal(overlay.back_requested, timeout=1000):
        overlay._back_button.click()


def test_forward_button_hidden_by_default_and_toggles(overlay: Overlay) -> None:
    """The forward button is hidden by default and shown via set_forward_visible."""
    assert overlay._forward_button.isHidden() is True
    overlay.set_forward_visible(True)
    assert overlay._forward_button.isHidden() is False


def test_forward_button_emits_forward_requested(overlay: Overlay, qtbot) -> None:
    """Activating the forward button emits ``forward_requested``."""
    with qtbot.waitSignal(overlay.forward_requested, timeout=1000):
        overlay._forward_button.click()


def test_model_selector_populates_and_emits_on_user_pick(overlay: Overlay, qtbot) -> None:
    """set_models fills the selector; a user pick emits ``model_changed``."""
    overlay.set_models(["m1", "m2"], "m2")
    assert overlay.selected_model() == "m2"
    with qtbot.waitSignal(overlay.model_changed, timeout=1000) as blocker:
        overlay._model_combo.textActivated.emit("m1")  # simulate a user selection
    assert blocker.args == ["m1"]


def test_set_models_does_not_emit(overlay: Overlay, qtbot) -> None:
    """Populating the selector programmatically does not emit ``model_changed``."""
    with qtbot.assertNotEmitted(overlay.model_changed):
        overlay.set_models(["a", "b"], "b")
    assert overlay.selected_model() == "b"


def test_language_selector_reflects_and_emits(overlay: Overlay, qtbot) -> None:
    """set_language updates the selector; a user pick emits ``language_changed``."""
    overlay.set_language("ru")
    assert overlay.selected_language() == "ru"
    with qtbot.waitSignal(overlay.language_changed, timeout=1000) as blocker:
        overlay._lang_combo.textActivated.emit("en")
    assert blocker.args == ["en"]


def test_copy_button_copies_question_and_answer(overlay: Overlay) -> None:
    """The copy button puts the question + answer (without ** markers) on the clipboard."""
    overlay.set_question("Вопрос?")
    overlay.show_answer("**Термин**: текст")
    overlay._copy_button.click()
    clip = QApplication.clipboard().text()
    assert "Вопрос?" in clip
    assert "Термин" in clip
    assert "**" not in clip


def test_copy_button_shows_feedback_then_reverts(overlay: Overlay) -> None:
    """Copying flips the button to ✓ briefly, then it reverts to 📋."""
    overlay.set_question("Q")
    overlay.show_answer("ответ")
    overlay._copy_button.click()
    assert overlay._copy_button.text() == "✓"
    overlay._reset_copy_button()
    assert overlay._copy_button.text() == "📋"


def test_answer_lives_in_a_scroll_area(overlay: Overlay) -> None:
    """The answer label is wrapped in a resizable scroll area (long answers scroll)."""
    assert overlay._answer_scroll.widget() is overlay._answer_label
    assert overlay._answer_scroll.widgetResizable() is True


def test_render_strips_think_blocks(overlay: Overlay) -> None:
    """``<think>…</think>`` reasoning is removed from the rendered answer."""
    overlay.show_answer("<think>скрытые рассуждения</think>\n**Ответ**: текст")
    assert "think" not in overlay.answer_raw()
    assert "рассуждения" not in overlay.answer_raw()
    assert "Ответ" in overlay.answer_raw()


def test_language_combo_has_a_min_width(overlay: Overlay) -> None:
    """The language selector has a sensible minimum width (was clipped)."""
    assert overlay._lang_combo.minimumWidth() >= 48


# --------------------------------------------------------------------------- #
# Tag cloud
# --------------------------------------------------------------------------- #
def test_end_answer_collects_tags_from_terms(overlay: Overlay) -> None:
    """Finishing an answer populates the tag cloud from its **bold** / `code` terms."""
    overlay.begin_answer()
    overlay.append_answer("1. **MVC**: про `Active Record` и `thread`")
    overlay.end_answer()
    assert overlay.tags() == ["MVC", "Active Record", "thread"]  # order of appearance, newest first


def test_tags_render_as_chip_buttons(overlay: Overlay) -> None:
    """Each tag becomes a clickable chip button in the flow layout."""
    overlay.add_tags(["REST", "thread"])
    chips = overlay._tags_container.findChildren(type(overlay._copy_button), "tagChip")
    labels = {c.text() for c in chips}
    assert {"REST", "thread"} <= labels


def test_hiding_transcript_drops_tags_to_the_bottom(overlay: Overlay, qtbot) -> None:
    """The answer stretches so tags+transcript stay at the bottom; hiding drops tags lower."""
    overlay.resize(400, 600)
    overlay.show()
    qtbot.waitExposed(overlay)
    overlay.add_tags(["REST"])

    overlay.set_transcript_visible(True)
    qtbot.waitUntil(lambda: overlay._transcript.isVisible(), timeout=1000)
    tags_y_shown = overlay._tags_container.mapTo(overlay, overlay._tags_container.rect().topLeft()).y()

    overlay.set_transcript_visible(False)
    qtbot.waitUntil(lambda: not overlay._transcript.isVisible(), timeout=1000)
    tags_y_hidden = overlay._tags_container.mapTo(overlay, overlay._tags_container.rect().topLeft()).y()

    # With the transcript hidden, the tag cloud moves further down (toward the controls).
    assert tags_y_hidden >= tags_y_shown
    assert overlay._transcript.isVisible() is False


def test_tag_chips_are_displayed_alphabetically(overlay: Overlay) -> None:
    """Chips render in case-insensitive alphabetical order regardless of insertion order."""
    overlay.add_tags(["thread", "Active Record", "mutex"])
    chips = overlay._tags_container.findChildren(type(overlay._copy_button), "tagChip")
    # findChildren preserves child-creation order, which is the render order.
    rendered = [c.text() for c in chips]
    assert rendered == sorted(rendered, key=str.lower)
    assert rendered == ["Active Record", "mutex", "thread"]


def test_add_tags_dedups_prepends_and_caps_at_20(overlay: Overlay) -> None:
    """New unique tags go to the front; duplicates are ignored; list is capped at 20."""
    overlay.add_tags(["a", "b"])
    overlay.add_tags(["b", "c"])  # b is a dup
    assert overlay.tags()[:3] == ["c", "a", "b"]
    overlay.add_tags([f"t{i}" for i in range(30)])
    assert len(overlay.tags()) == 20


def test_tag_chip_click_emits_term_activated(overlay: Overlay, qtbot) -> None:
    """Clicking a tag chip drills down via the ``term_activated`` signal."""
    overlay.add_tags(["REST"])
    chip = overlay._tags_container.findChildren(type(overlay._copy_button), "tagChip")[0]
    with qtbot.waitSignal(overlay.term_activated, timeout=1000) as blocker:
        chip.click()
    assert blocker.args == ["REST"]


def test_transcript_words_are_clickable_links() -> None:
    """Words are links; "·" between words = pair; "•" at sentence end = whole sentence."""
    from urllib.parse import quote

    html_line = Overlay._linkify_words("расскажи про REST")
    # 3 word links + 2 between-word pair dots + 1 sentence dot.
    assert html_line.count('href="term:') == 6
    assert "·" in html_line  # pair dots
    assert "•" in html_line  # sentence dot
    assert f'href="term:{quote("расскажи про")}"' in html_line  # pair link


def test_transcript_sentence_dot_links_whole_sentence() -> None:
    """The "•" at a sentence end carries the whole sentence."""
    from urllib.parse import quote

    html_line = Overlay._linkify_words("Что такое REST?")
    assert f'href="term:{quote("Что такое REST?")}"' in html_line


def test_clear_button_empties_the_transcript(overlay: Overlay) -> None:
    """The 'Очистить' button clears the recognition feed."""
    overlay.append_transcript("первая фраза")
    overlay.append_transcript("вторая фраза")
    assert overlay._transcript.toPlainText() != ""
    overlay._clear_transcript_button.click()
    assert overlay._transcript.toPlainText() == ""


def test_transcript_preserves_leading_and_trailing_punctuation() -> None:
    """Punctuation around a word (quotes, brackets, commas) is kept, not dropped."""
    html_line = Overlay._linkify_words("он сказал «привет», (REST)")
    for ch in ("«", "»", ",", "(", ")"):
        assert ch in html_line
    # The words themselves are still links.
    assert ">привет</a>" in html_line
    assert ">REST</a>" in html_line


def test_transcript_hover_recolor_does_not_crash(overlay: Overlay) -> None:
    """Hovering a transcript link recolours it and restores on leave without error."""
    from urllib.parse import quote

    from PyQt6.QtCore import QUrl

    overlay.append_transcript("что такое mutex")
    overlay._on_transcript_hover(QUrl(f"term:{quote('mutex')}"))  # hover a word
    assert overlay._hovered  # something got recoloured
    overlay._on_transcript_hover(QUrl(""))  # leave restores
    assert overlay._hovered == []


def test_selection_fills_input_field(overlay: Overlay) -> None:
    """A non-empty selection is normalized and dropped into the manual-input field."""
    overlay._selection_to_input("два  слова\nтретье")
    assert overlay._input_field.text() == "два слова третье"


def test_empty_selection_does_not_overwrite_input(overlay: Overlay) -> None:
    """An empty/whitespace selection leaves the input field untouched."""
    overlay._input_field.setText("моё")
    overlay._selection_to_input("   ")
    assert overlay._input_field.text() == "моё"


def test_transcript_anchor_click_emits_term_activated(overlay: Overlay, qtbot) -> None:
    """Clicking a word in the transcript drills down via ``term_activated``."""
    from PyQt6.QtCore import QUrl

    overlay.append_transcript("что такое mutex")
    with qtbot.waitSignal(overlay.term_activated, timeout=1000) as blocker:
        overlay._transcript.anchorClicked.emit(QUrl("term:mutex"))
    assert blocker.args == ["mutex"]


def test_pin_button_toggles_and_emits(overlay: Overlay, qtbot) -> None:
    """The pin button is off by default, emits ``pin_toggled`` and reflects set_pinned."""
    assert overlay.is_pinned() is False
    with qtbot.waitSignal(overlay.pin_toggled, timeout=1000) as blocker:
        overlay._pin_button.click()
    assert blocker.args == [True]
    assert overlay.is_pinned() is True
    overlay.set_pinned(False)
    assert overlay.is_pinned() is False
