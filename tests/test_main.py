# tests/test_main.py

"""Tests for application wiring (``build_app``)."""

from unittest.mock import MagicMock

from main import build_app
from src.core.controller import Controller
from src.core.hotkeys import HotkeyManager
from src.models.enums import Mode
from src.ui.overlay import Overlay


def test_build_app_wires_components(qtbot) -> None:
    fake_claude = MagicMock()

    overlay, controller, hotkeys = build_app(claude=fake_claude)
    qtbot.addWidget(overlay)

    assert isinstance(overlay, Overlay)
    assert isinstance(controller, Controller)
    assert isinstance(hotkeys, HotkeyManager)
    assert controller.mode in (Mode.COACH, Mode.ANSWER)
    assert len(hotkeys.bindings) == 3


def test_build_app_uses_injected_claude(qtbot) -> None:
    fake_claude = MagicMock()

    _, controller, _ = build_app(claude=fake_claude)

    # The injected client is the one the controller will stream from.
    assert controller._claude is fake_claude  # noqa: SLF001  (white-box wiring check)


def test_maybe_start_speech_disabled_when_backend_missing(monkeypatch) -> None:
    import main as main_module

    # Force "mlx_whisper not installed" so STT is disabled — deterministic regardless
    # of whether mlx-whisper happens to be installed, and never opens a real microphone.
    monkeypatch.setattr(main_module.importlib.util, "find_spec", lambda name: None)
    assert main_module._maybe_start_speech(MagicMock()) is None


def test_maybe_start_speech_starts_pipeline(monkeypatch) -> None:
    import main as main_module

    monkeypatch.setattr(main_module.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(main_module, "create_engine", lambda *a, **k: MagicMock())
    started: dict[str, bool] = {}

    class _FakePipeline:
        def __init__(self, engine, *, on_partial_text, on_final_text, on_level=None, device=None) -> None:
            started["init"] = True

        def start(self) -> None:
            started["start"] = True

        def stop(self) -> None:
            started["stop"] = True

    monkeypatch.setattr(main_module, "SpeechPipeline", _FakePipeline)

    pipeline = main_module._maybe_start_speech(MagicMock())

    assert started.get("start") is True
    assert pipeline is not None
