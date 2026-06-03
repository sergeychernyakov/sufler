# tests/core/test_hotkeys.py

"""Tests for the pynput-to-Qt HotkeyManager (no real global listener)."""

from unittest.mock import MagicMock

from src.core.hotkeys import HotkeyManager


def _make() -> HotkeyManager:
    return HotkeyManager(
        capture_hotkey="<cmd>+<shift>+s",
        panic_hotkey="<cmd>+<shift>+h",
        last_hotkey="<cmd>+<shift>+a",
    )


def test_bindings_map_to_the_three_hotkeys() -> None:
    manager = _make()
    assert set(manager.bindings) == {"<cmd>+<shift>+s", "<cmd>+<shift>+h", "<cmd>+<shift>+a"}


def test_invoking_a_binding_emits_its_signal() -> None:
    manager = _make()
    fired: list[str] = []
    manager.capture.connect(lambda: fired.append("capture"))
    manager.panic.connect(lambda: fired.append("panic"))
    manager.answer_last.connect(lambda: fired.append("last"))

    manager.bindings["<cmd>+<shift>+s"]()
    manager.bindings["<cmd>+<shift>+h"]()
    manager.bindings["<cmd>+<shift>+a"]()

    assert fired == ["capture", "panic", "last"]


def test_start_and_stop_drive_the_listener(monkeypatch) -> None:
    from pynput import keyboard

    fake_listener = MagicMock()
    monkeypatch.setattr(keyboard, "GlobalHotKeys", lambda bindings: fake_listener)

    manager = _make()
    manager.start()
    fake_listener.start.assert_called_once()

    manager.stop()
    fake_listener.stop.assert_called_once()


def test_stop_without_start_is_safe() -> None:
    manager = _make()
    manager.stop()  # should not raise
