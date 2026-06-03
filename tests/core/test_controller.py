# tests/core/test_controller.py

"""Tests for the Controller orchestration (input -> screenshot -> Claude -> overlay)."""

import pytest

from src.core.context import RollingContext
from src.core.controller import CAPTURE_PROMPT, Controller
from src.models.enums import Mode


class _FakeOverlay:
    """Records the controller's calls; real methods so Qt signals can connect to it."""

    def __init__(self) -> None:
        self.questions: list[str] = []
        self.answer_tokens: list[str] = []
        self.transcript: list[str] = []
        self.levels: list[float] = []
        self.shown_answers: list[str] = []
        self.back_visible = False
        self.begun = 0
        self.ended = 0
        self.hidden = 0
        self.shown = 0
        self.panicked = 0
        self.mode = None

    def set_question(self, text: str) -> None:
        self.questions.append(text)

    def begin_answer(self) -> None:
        self.begun += 1

    def end_answer(self) -> None:
        self.ended += 1

    def append_answer(self, token: str) -> None:
        self.answer_tokens.append(token)

    def append_transcript(self, text: str) -> None:
        self.transcript.append(text)

    def set_input_level(self, level: float) -> None:
        self.levels.append(level)

    def set_back_visible(self, visible: bool) -> None:
        self.back_visible = visible

    def answer_raw(self) -> str:
        return "".join(self.answer_tokens)

    def show_answer(self, raw: str) -> None:
        self.shown_answers.append(raw)

    def hide(self) -> None:
        self.hidden += 1

    def show(self) -> None:
        self.shown += 1

    def panic_hide(self) -> None:
        self.panicked += 1

    def set_mode(self, mode) -> None:
        self.mode = mode


class _FakeClaude:
    """Returns canned tokens and records each stream_answer call."""

    def __init__(self, tokens) -> None:
        self.tokens = tokens
        self.calls: list[dict] = []

    def stream_answer(self, question, *, image_b64=None, context=None, mode=Mode.COACH):
        self.calls.append({"question": question, "image_b64": image_b64, "context": context, "mode": mode})
        return iter(self.tokens)


def _make(tokens=("a", "b"), grab=lambda: "IMG"):
    overlay = _FakeOverlay()
    claude = _FakeClaude(list(tokens))
    context = RollingContext()
    controller = Controller(
        overlay,
        claude,
        context,
        grab_screen=grab,
        runner=lambda work: work(),  # synchronous
        hide_delay=0.0,
    )
    return controller, overlay, claude, context


def test_on_capture_hides_grabs_shows_and_streams() -> None:
    controller, overlay, claude, _ = _make()
    controller.on_capture()
    assert overlay.hidden == 1
    assert overlay.shown == 1
    assert overlay.begun == 1
    assert overlay.answer_tokens == ["a", "b"]
    assert claude.calls[0]["image_b64"] == "IMG"
    assert claude.calls[0]["question"] == CAPTURE_PROMPT


def test_on_submit_text_streams_without_screenshot() -> None:
    controller, overlay, claude, context = _make()
    controller.on_submit_text("  что такое GIL  ")
    assert claude.calls[0]["question"] == "что такое GIL"
    assert claude.calls[0]["image_b64"] is None
    assert context.last_question() == "что такое GIL"
    assert overlay.answer_tokens == ["a", "b"]


def test_on_submit_text_ignores_blank() -> None:
    controller, _, claude, _ = _make()
    controller.on_submit_text("    ")
    assert claude.calls == []


def test_on_answer_last_uses_recent_speech() -> None:
    controller, _, claude, context = _make()
    context.add_speech("расскажи про индексы в postgres")
    controller.on_answer_last()
    assert "индексы" in claude.calls[0]["question"]
    assert claude.calls[0]["image_b64"] is None


def test_on_answer_last_without_context_is_noop() -> None:
    controller, overlay, claude, _ = _make()
    controller.on_answer_last()
    assert claude.calls == []
    assert overlay.questions[-1] == "(нет распознанной речи)"


def test_panic_hides_overlay() -> None:
    controller, overlay, _, _ = _make()
    controller.panic()
    assert overlay.panicked == 1


def test_set_mode_updates_controller_and_overlay() -> None:
    controller, overlay, _, _ = _make()
    controller.set_mode(Mode.ANSWER)
    assert controller.mode == Mode.ANSWER
    assert overlay.mode == Mode.ANSWER


def test_screenshot_failure_still_restores_overlay_and_streams() -> None:
    def boom() -> str:
        raise RuntimeError("screencapture exploded")

    controller, overlay, claude, _ = _make(grab=boom)
    controller.on_capture()
    assert overlay.shown == 1  # restored despite failure
    assert claude.calls[0]["image_b64"] is None


def test_claude_error_emits_error_token() -> None:
    class _Boom:
        def stream_answer(self, *a, **k):
            raise RuntimeError("api down")

    overlay = _FakeOverlay()
    controller = Controller(
        overlay, _Boom(), RollingContext(), grab_screen=lambda: "IMG", runner=lambda w: w(), hide_delay=0.0
    )
    controller.on_submit_text("hi")
    assert any("ошибка" in tok for tok in overlay.answer_tokens)


def test_partial_speech_shows_draft_question() -> None:
    controller, overlay, _, _ = _make()
    controller.partial_speech.emit("черновик вопроса")
    assert overlay.questions[-1] == "черновик вопроса"


def test_final_speech_records_into_context() -> None:
    controller, overlay, _, context = _make()
    controller.final_speech.emit("расскажи про сборщик мусора")
    assert context.last_question() == "расскажи про сборщик мусора"
    assert "сборщик" in context.recent_speech()
    assert overlay.questions[-1] == "расскажи про сборщик мусора"


class _FakePipeline:
    """Records set_listening calls so the mic-toggle wiring can be asserted."""

    def __init__(self) -> None:
        self.calls: list[bool] = []

    def set_listening(self, listening: bool) -> None:
        self.calls.append(listening)


def test_on_mic_toggled_forwards_to_attached_pipeline() -> None:
    controller, _, _, _ = _make()
    pipeline = _FakePipeline()
    controller.set_speech_pipeline(pipeline)

    controller.on_mic_toggled(False)
    controller.on_mic_toggled(True)

    assert pipeline.calls == [False, True]


def test_on_mic_toggled_without_pipeline_is_noop() -> None:
    controller, _, _, _ = _make()
    controller.on_mic_toggled(False)  # no pipeline attached -> must not raise


def test_speech_level_updates_overlay_meter() -> None:
    controller, overlay, _, _ = _make()
    controller.speech_level.emit(0.42)
    assert overlay.levels == [pytest.approx(0.42)]


def test_on_input_volume_changed_forwards_to_setter() -> None:
    overlay = _FakeOverlay()
    calls: list[int] = []
    controller = Controller(
        overlay,
        _FakeClaude([]),
        RollingContext(),
        runner=lambda work: work(),
        set_input_volume=lambda percent: calls.append(percent) or True,
    )
    controller.on_input_volume_changed(42)
    assert calls == [42]


def test_final_speech_auto_answers_when_enabled() -> None:
    controller, _, claude, _ = _make()  # auto_answer defaults on
    controller.final_speech.emit("что такое REST?")
    assert claude.calls and "REST" in claude.calls[0]["question"]


def test_final_speech_does_not_answer_when_auto_off() -> None:
    overlay = _FakeOverlay()
    claude = _FakeClaude(["a"])
    controller = Controller(overlay, claude, RollingContext(), runner=lambda w: w(), auto_answer=False)
    controller.final_speech.emit("что такое REST?")
    assert claude.calls == []


def test_term_click_drills_down_and_shows_back() -> None:
    controller, overlay, claude, _ = _make()
    controller.on_submit_text("Расскажи про Rails")
    controller.on_term_clicked("Active Record")
    assert "Active Record" in claude.calls[-1]["question"]
    assert overlay.back_visible is True


def test_back_restores_previous_answer() -> None:
    controller, overlay, _, _ = _make()
    controller.on_submit_text("Расскажи про Rails")  # answer tokens -> "ab"
    controller.on_term_clicked("Active Record")
    controller.on_back()
    assert overlay.shown_answers[-1] == "ab"
    assert overlay.back_visible is False


def test_back_without_history_is_noop() -> None:
    controller, overlay, _, _ = _make()
    controller.on_back()
    assert overlay.shown_answers == []


def test_new_question_clears_drill_history() -> None:
    controller, overlay, _, _ = _make()
    controller.on_submit_text("Q1")
    controller.on_term_clicked("term")  # back becomes visible
    controller.on_submit_text("Q2")  # new root clears history
    assert overlay.back_visible is False
    controller.on_back()  # nothing to restore
    assert overlay.shown_answers == []
