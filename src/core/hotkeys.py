# src/core/hotkeys.py
# pylint: disable=no-name-in-module,c-extension-no-member

"""Global hotkeys (pynput) bridged to Qt signals.

pynput's listener runs on its own thread, so each hotkey emits a Qt signal; the
main application connects those signals to controller methods, which Qt then
delivers on the UI thread. Requires macOS Accessibility permission to work.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from src.helpers.logger import get_logger

logger = get_logger(__name__)


class HotkeyManager(QObject):
    """Maps configured hotkeys to Qt signals and runs the pynput listener."""

    capture = pyqtSignal()
    panic = pyqtSignal()
    answer_last = pyqtSignal()

    def __init__(self, *, capture_hotkey: str, panic_hotkey: str, last_hotkey: str) -> None:
        """Builds the hotkey → signal bindings.

        Args:
            capture_hotkey (str): pynput hotkey for screenshot capture (e.g. ``<cmd>+<shift>+s``).
            panic_hotkey (str): pynput hotkey to instantly hide the overlay.
            last_hotkey (str): pynput hotkey to answer from recent speech.
        """
        super().__init__()
        self._bindings: Dict[str, Callable[[], None]] = {
            capture_hotkey: self.capture.emit,
            panic_hotkey: self.panic.emit,
            last_hotkey: self.answer_last.emit,
        }
        self._listener: Optional[object] = None

    @property
    def bindings(self) -> Dict[str, Callable[[], None]]:
        """Returns the hotkey → emitter mapping (read-only view)."""
        return dict(self._bindings)

    def start(self) -> None:
        """Starts the global pynput listener (needs Accessibility permission)."""
        from pynput import keyboard  # lazy: importing the backend needs no permission

        listener = keyboard.GlobalHotKeys(self._bindings)
        listener.start()
        self._listener = listener
        logger.info("Global hotkeys active: %s", ", ".join(self._bindings))

    def stop(self) -> None:
        """Stops the global listener if running."""
        listener = self._listener
        if listener is not None and hasattr(listener, "stop"):
            listener.stop()
            self._listener = None
