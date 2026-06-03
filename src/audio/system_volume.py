# src/audio/system_volume.py

"""Read and adjust the macOS **system input (microphone) volume**.

The overlay exposes a slider so the user can change the microphone input gain
without opening System Settings → Sound → Input. macOS has no lightweight public
Python API for this, so we drive it through the built-in ``osascript`` AppleScript
bridge:

* read  — ``input volume of (get volume settings)`` → ``0..100``
* write — ``set volume input volume <0..100>``

Both act on the **default** input device (the one selected in System Settings),
which is what the built-in microphone uses; a non-default loopback device
(e.g. BlackHole) is not affected by this control.
"""

import subprocess  # nosec B404 - osascript is a fixed, first-party macOS binary path.
from typing import Optional

from src.helpers.logger import get_logger

logger = get_logger(__name__)

#: Absolute path to the macOS AppleScript runner.
OSASCRIPT_BIN = "/usr/bin/osascript"

#: Timeout (seconds) for the short AppleScript calls.
_TIMEOUT_SECONDS = 5


def get_input_volume() -> Optional[int]:
    """Return the current system input volume as ``0..100``, or ``None`` if unknown.

    Returns:
        Optional[int]: The default input device's volume in percent, or ``None``
        when it cannot be read (no ``osascript``, a device reporting
        ``missing value``, or any error).
    """
    try:
        result = subprocess.run(  # nosec B603 - fixed osascript binary; the script is a literal.
            [OSASCRIPT_BIN, "-e", "input volume of (get volume settings)"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("Could not read system input volume")
        return None
    value = result.stdout.strip()
    return int(value) if value.isdigit() else None


def set_input_volume(percent: int) -> bool:
    """Set the system input volume (clamped to ``0..100``).

    Args:
        percent (int): Desired input volume in percent; values outside ``0..100``
            are clamped.

    Returns:
        bool: ``True`` if the change was applied, ``False`` on any error.
    """
    clamped = max(0, min(100, int(percent)))
    try:
        subprocess.run(  # nosec B603 - fixed osascript binary; volume is a clamped int.
            [OSASCRIPT_BIN, "-e", f"set volume input volume {clamped}"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("Could not set system input volume")
        return False
    logger.debug("System input volume set to %d%%", clamped)
    return True
