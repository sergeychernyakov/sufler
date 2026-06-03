# tests/audio/test_system_volume.py

"""Unit tests for :mod:`src.audio.system_volume`.

``subprocess.run`` is mocked throughout — no real ``osascript`` is invoked, so the
tests never touch (or change) the machine's actual input volume. They follow the
Arrange -> Act -> Assert pattern.
"""

import subprocess
from unittest.mock import MagicMock, patch

from src.audio import system_volume


def test_get_input_volume_parses_integer() -> None:
    """A numeric ``osascript`` result is parsed into an int."""
    # Arrange
    result = MagicMock(stdout="55\n")

    # Act
    with patch("src.audio.system_volume.subprocess.run", return_value=result) as run:
        value = system_volume.get_input_volume()

    # Assert
    assert value == 55
    run.assert_called_once()


def test_get_input_volume_non_numeric_returns_none() -> None:
    """A non-numeric result (e.g. ``missing value``) yields ``None``."""
    # Arrange
    result = MagicMock(stdout="missing value\n")

    # Act / Assert
    with patch("src.audio.system_volume.subprocess.run", return_value=result):
        assert system_volume.get_input_volume() is None


def test_get_input_volume_error_returns_none() -> None:
    """A subprocess failure yields ``None`` rather than raising."""
    # Act / Assert
    with patch("src.audio.system_volume.subprocess.run", side_effect=OSError("no osascript")):
        assert system_volume.get_input_volume() is None


def test_set_input_volume_clamps_and_invokes_osascript() -> None:
    """Out-of-range values are clamped and passed to ``set volume input volume``."""
    # Act
    with patch("src.audio.system_volume.subprocess.run", return_value=MagicMock()) as run:
        ok = system_volume.set_input_volume(150)

    # Assert
    assert ok is True
    argv = run.call_args.args[0]
    assert argv[0] == system_volume.OSASCRIPT_BIN
    assert argv[-1] == "set volume input volume 100"


def test_set_input_volume_error_returns_false() -> None:
    """A subprocess error makes ``set_input_volume`` return ``False``."""
    # Arrange
    err = subprocess.CalledProcessError(1, "osascript")

    # Act / Assert
    with patch("src.audio.system_volume.subprocess.run", side_effect=err):
        assert system_volume.set_input_volume(50) is False
