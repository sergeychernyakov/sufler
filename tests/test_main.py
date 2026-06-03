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
