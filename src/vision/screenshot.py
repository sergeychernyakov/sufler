# src/vision/screenshot.py

"""
Screen Capture Service

This module captures the current screen (or a sub-region of it) and returns the
result as a base64-encoded PNG suitable for sending to a multimodal Claude
model (Phase 2).

Capture strategy:
    1. **Primary** – the native macOS ``screencapture`` binary is invoked via
       ``subprocess`` (``screencapture -x [-R x,y,w,h] <tmpfile>``). It is fast,
       respects Screen Recording permissions, and avoids extra dependencies.
    2. **Fallback** – if ``screencapture`` is missing or fails for any reason,
       the pure-Python :mod:`mss` library is used instead.

Hiding the overlay window before a capture is the controller's responsibility
and is intentionally *not* handled here; this module is pure capture.
"""

import base64
import subprocess  # nosec B404 - screencapture is a fixed, first-party macOS binary path.
import uuid
from pathlib import Path

from src.helpers.logger import get_logger

logger = get_logger(__name__)

Region = tuple[int, int, int, int]

#: Absolute path to the native macOS screenshot binary.
SCREENCAPTURE_BIN = "/usr/sbin/screencapture"

#: Directory used for short-lived temporary PNG files.
TMP_DIR = Path("tmp")


def grab_screen(region: Region | None = None) -> str:
    """Capture the screen (or a region) and return a base64-encoded PNG.

    The native ``screencapture`` binary is tried first; if it is unavailable or
    fails, capture falls back to :mod:`mss`. The temporary PNG written by the
    native path is always removed before returning.

    Args:
        region (tuple[int, int, int, int] | None): Optional ``(x, y, w, h)``
            rectangle in screen coordinates. When ``None`` the entire screen is
            captured.

    Returns:
        str: The captured image encoded as a base64 PNG string (ASCII).

    Raises:
        RuntimeError: If both the native and ``mss`` capture paths fail.
    """
    try:
        png_bytes = _capture_with_screencapture(region)
        logger.debug("Captured screen via screencapture (region=%s)", region)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("screencapture unavailable or failed (%s); falling back to mss", exc)
        png_bytes = _capture_with_mss(region)
        logger.debug("Captured screen via mss fallback (region=%s)", region)

    return _png_bytes_to_base64(png_bytes)


def _capture_with_screencapture(region: Region | None) -> bytes:
    """Capture the screen using the native macOS ``screencapture`` binary.

    A unique temporary PNG is written under :data:`TMP_DIR`, read back into
    memory, and deleted before returning.

    Args:
        region (tuple[int, int, int, int] | None): Optional ``(x, y, w, h)``
            rectangle to capture; ``None`` captures the whole screen.

    Returns:
        bytes: The raw PNG bytes produced by ``screencapture``.

    Raises:
        OSError: If the temporary file cannot be written or the PNG is empty.
        subprocess.SubprocessError: If ``screencapture`` exits non-zero (raised
            via :meth:`subprocess.CompletedProcess.check_returncode`).
    """
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = TMP_DIR / f"screenshot_{uuid.uuid4().hex}.png"

    command = [SCREENCAPTURE_BIN, "-x"]
    if region is not None:
        command += ["-R", _build_region_arg(region)]
    command.append(str(tmp_path))

    try:
        # ``-x`` suppresses the capture sound; the binary path is fixed/first-party.
        result = subprocess.run(command, capture_output=True, check=False)  # nosec B603
        result.check_returncode()

        png_bytes = tmp_path.read_bytes()
        if not png_bytes:
            raise OSError("screencapture produced an empty file")
        return png_bytes
    finally:
        tmp_path.unlink(missing_ok=True)


def _capture_with_mss(region: Region | None) -> bytes:
    """Capture the screen using the pure-Python :mod:`mss` fallback.

    Args:
        region (tuple[int, int, int, int] | None): Optional ``(x, y, w, h)``
            rectangle to capture; ``None`` captures the primary monitor.

    Returns:
        bytes: The captured image encoded as PNG bytes.

    Raises:
        RuntimeError: If :mod:`mss` fails to produce PNG bytes.
    """
    import mss  # pylint: disable=import-outside-toplevel
    import mss.tools  # pylint: disable=import-outside-toplevel

    with mss.mss() as sct:
        if region is not None:
            x, y, width, height = region
            monitor = {"left": x, "top": y, "width": width, "height": height}
        else:
            # ``monitors[0]`` is the virtual bounding box across all displays.
            monitor = sct.monitors[0]

        shot = sct.grab(monitor)
        png_bytes = mss.tools.to_png(shot.rgb, shot.size)

    if not png_bytes:
        raise RuntimeError("mss failed to encode the screenshot as PNG")
    return png_bytes


def _build_region_arg(region: Region) -> str:
    """Build the ``screencapture`` ``-R`` value from a region tuple.

    Args:
        region (tuple[int, int, int, int]): The ``(x, y, w, h)`` rectangle.

    Returns:
        str: A comma-joined ``"x,y,w,h"`` string for the ``-R`` flag.
    """
    x, y, width, height = region
    return f"{x},{y},{width},{height}"


def _png_bytes_to_base64(data: bytes) -> str:
    """Encode raw PNG bytes as a base64 ASCII string.

    Args:
        data (bytes): The raw PNG bytes.

    Returns:
        str: The base64-encoded representation of ``data``.
    """
    return base64.b64encode(data).decode("ascii")
