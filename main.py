# main.py

"""Application entry point.

Wires configuration, the stealth overlay, the Claude client, rolling context, the
controller and global hotkeys into a runnable app. ``build_app`` performs the
wiring (and is unit-tested); ``main`` owns the blocking Qt event loop.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Optional

from PyQt6 import QtGui, QtWidgets

from src.audio.devices import resolve_input_device
from src.audio.pipeline import SpeechPipeline
from src.audio.stt import create_engine
from src.config import config
from src.core.context import RollingContext
from src.core.controller import Controller
from src.core.hotkeys import HotkeyManager
from src.helpers.logger import get_logger
from src.llm.claude import ClaudeClient
from src.models.enums import Mode, SttEngine
from src.ui.overlay import Overlay

logger = get_logger(__name__)

#: App icon (also bundled as sufler.icns by ``bin/make_app``). Setting it on the
#: QApplication gives the window and Dock tile a real icon when run via ``python main.py``.
_ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.png"


def _resolve_mode() -> Mode:
    """Returns the configured answer mode, defaulting to coach on bad input."""
    try:
        return Mode(config.mode)
    except ValueError:
        logger.warning("Unknown SUFLER_MODE=%r; falling back to coach", config.mode)
        return Mode.COACH


def build_app(*, claude: Optional[ClaudeClient] = None) -> tuple[Overlay, Controller, HotkeyManager]:
    """Constructs and wires every component without starting the event loop.

    Args:
        claude (Optional[ClaudeClient]): Injected client (tests); defaults to a
            real :class:`ClaudeClient` built from configuration.

    Returns:
        tuple[Overlay, Controller, HotkeyManager]: The wired top-level objects.
    """
    if not config.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY is empty — captures will fail until it is set in .env")

    overlay = Overlay(stealth=config.stealth)
    claude_client = claude or ClaudeClient(api_key=config.anthropic_api_key or "MISSING_API_KEY")
    context = RollingContext()
    controller = Controller(overlay, claude_client, context, mode=_resolve_mode())

    overlay.capture_requested.connect(controller.on_capture)
    overlay.text_submitted.connect(controller.on_submit_text)

    hotkeys = HotkeyManager(
        capture_hotkey=config.hotkey_capture,
        panic_hotkey=config.hotkey_panic,
        last_hotkey=config.hotkey_last,
    )
    hotkeys.capture.connect(controller.on_capture)
    hotkeys.panic.connect(controller.panic)
    hotkeys.answer_last.connect(controller.on_answer_last)

    return overlay, controller, hotkeys


def _resolve_loopback_device() -> Optional[int]:
    """Resolves the configured loopback input device, falling back to the default.

    Returns:
        Optional[int]: The resolved input-device index, or ``None`` for the system
        default (also returned, with a warning, when the configured device is absent).
    """
    try:
        return resolve_input_device(config.loopback_device or None)
    except ValueError:
        logger.warning(
            "Loopback device %r not found — install BlackHole or fix SUFLER_LOOPBACK_DEVICE; "
            "using the default input device instead.",
            config.loopback_device,
        )
        return None


def _maybe_start_speech(controller: Controller) -> Optional[SpeechPipeline]:
    """Starts live speech capture if the STT backend is available.

    Args:
        controller (Controller): Receives partial/final speech via its signals.

    Returns:
        Optional[SpeechPipeline]: The running pipeline, or ``None`` when STT is
        disabled (backend missing) or the microphone could not be opened.
    """
    if config.stt_engine == SttEngine.MLX.value and importlib.util.find_spec("mlx_whisper") is None:
        logger.warning("STT disabled: run `pip install mlx-whisper` to enable live speech")
        return None
    try:
        device = _resolve_loopback_device()
        pipeline = SpeechPipeline(
            create_engine(),
            on_partial_text=controller.partial_speech.emit,
            on_final_text=controller.final_speech.emit,
            device=device,
        )
        pipeline.start()
        logger.info("Live STT active (engine=%s, device=%s)", config.stt_engine, device)
        return pipeline
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Could not start live STT (microphone permission?)")
        return None


def main() -> int:  # pragma: no cover - launches the blocking Qt event loop
    """Builds the app, starts hotkeys and runs the Qt event loop."""
    logger.info("Starting sufler")
    app = QtWidgets.QApplication(sys.argv)
    if _ICON_PATH.exists():
        app.setWindowIcon(QtGui.QIcon(str(_ICON_PATH)))
    overlay, controller, hotkeys = build_app()
    logger.info("sufler ready (mode=%s)", controller.mode.value)

    try:
        hotkeys.start()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Could not start global hotkeys — grant Accessibility permission")

    overlay.show()
    overlay.raise_()
    pipeline = _maybe_start_speech(controller)
    try:
        return app.exec()
    finally:
        if pipeline is not None:
            pipeline.stop()
        hotkeys.stop()
        logger.info("sufler shutting down")


if __name__ == "__main__":
    sys.exit(main())
