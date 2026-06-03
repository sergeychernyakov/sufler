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
        self.begun = 0
        self.hidden = 0
        self.shown = 0
        self.panicked = 0
        self.mode = None

    def set_question(self, text: str) -> None:
        self.questions.append(text)

    def begin_answer(self) -> None:
        self.begun += 1

    def append_answer(self, token: str) -> None:
        self.answer_tokens.append(token)

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
