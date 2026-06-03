# tests/vision/test_screenshot.py

"""
Unit tests for :mod:`src.vision.screenshot`.

These tests never take a real screenshot: ``subprocess.run``, filesystem reads
and the :mod:`mss` library are all mocked. They follow the Arrange -> Act ->
Assert pattern and cover the happy path, region handling, both fallback
triggers (non-zero exit and raised exception) and the base64 round-trip.
"""

import base64
import subprocess
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from src.vision import screenshot

FAKE_NATIVE_PNG = b"\x89PNG\r\n\x1a\nnative-bytes"
FAKE_MSS_PNG = b"\x89PNG\r\n\x1a\nmss-fallback-bytes"


@pytest.fixture
def patched_fs() -> Iterator[dict[str, MagicMock]]:
    """Patch the filesystem helpers used by the native capture path.

    Yields:
        dict[str, MagicMock]: Mocks for ``mkdir``, ``read_bytes`` and
        ``unlink`` keyed by name, so tests can assert on them.
    """
    with (
        patch.object(screenshot.Path, "mkdir") as mkdir,
        patch.object(screenshot.Path, "read_bytes", return_value=FAKE_NATIVE_PNG) as read_bytes,
        patch.object(screenshot.Path, "unlink") as unlink,
    ):
        yield {"mkdir": mkdir, "read_bytes": read_bytes, "unlink": unlink}


def _completed(returncode: int) -> subprocess.CompletedProcess[bytes]:
    """Build a fake ``CompletedProcess`` with the given return code.

    Args:
        returncode (int): The exit status to simulate.

    Returns:
        subprocess.CompletedProcess[bytes]: A ready-to-use completed process.
    """
    return subprocess.CompletedProcess(args=["screencapture"], returncode=returncode, stdout=b"", stderr=b"")


def _make_mss(png_bytes: bytes) -> MagicMock:
    """Create a fake ``mss`` module whose capture yields ``png_bytes``.

    Args:
        png_bytes (bytes): The PNG payload ``mss.tools.to_png`` should return.

    Returns:
        MagicMock: A stand-in for the :mod:`mss` module wired so that
        ``mss.mss()`` is a context manager exposing ``grab`` and ``monitors``,
        and ``mss.tools.to_png`` returns ``png_bytes``.
    """
    fake_mss = MagicMock()
    sct = MagicMock()
    sct.monitors = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]
    sct.grab.return_value = MagicMock(rgb=b"raw-rgb", size=(1920, 1080))
    fake_mss.mss.return_value.__enter__.return_value = sct
    fake_mss.tools.to_png.return_value = png_bytes
    return fake_mss


# --------------------------------------------------------------------------- #
# Happy path: native screencapture
# --------------------------------------------------------------------------- #
def test_grab_screen_returns_base64_of_native_png(patched_fs: dict[str, MagicMock]) -> None:
    """A successful screencapture run returns base64 of the PNG file bytes."""
    # Arrange
    with patch.object(screenshot.subprocess, "run", return_value=_completed(0)) as run:
        # Act
        result = screenshot.grab_screen()

    # Assert
    assert result == base64.b64encode(FAKE_NATIVE_PNG).decode("ascii")
    run.assert_called_once()
    patched_fs["read_bytes"].assert_called_once()


def test_grab_screen_base64_round_trips_to_original_bytes(patched_fs: dict[str, MagicMock]) -> None:
    """Decoding the returned base64 string yields the exact original PNG bytes."""
    # Arrange
    with patch.object(screenshot.subprocess, "run", return_value=_completed(0)):
        # Act
        result = screenshot.grab_screen()

    # Assert
    assert base64.b64decode(result) == FAKE_NATIVE_PNG


def test_grab_screen_cleans_up_temp_file(patched_fs: dict[str, MagicMock]) -> None:
    """The temporary PNG is always unlinked after a native capture."""
    # Arrange
    with patch.object(screenshot.subprocess, "run", return_value=_completed(0)):
        # Act
        screenshot.grab_screen()

    # Assert
    patched_fs["unlink"].assert_called_once_with(missing_ok=True)


# --------------------------------------------------------------------------- #
# Command construction
# --------------------------------------------------------------------------- #
def test_full_screen_command_has_no_region_flag(patched_fs: dict[str, MagicMock]) -> None:
    """Without a region the command uses ``-x`` and omits ``-R``."""
    # Arrange
    with patch.object(screenshot.subprocess, "run", return_value=_completed(0)) as run:
        # Act
        screenshot.grab_screen()

    # Assert
    command = run.call_args.args[0]
    assert command[0] == screenshot.SCREENCAPTURE_BIN
    assert "-x" in command
    assert "-R" not in command


def test_region_builds_correct_minus_r_argument(patched_fs: dict[str, MagicMock]) -> None:
    """A region tuple becomes a ``-R x,y,w,h`` argument pair."""
    # Arrange
    region = (10, 20, 300, 400)
    with patch.object(screenshot.subprocess, "run", return_value=_completed(0)) as run:
        # Act
        screenshot.grab_screen(region=region)

    # Assert
    command = run.call_args.args[0]
    assert "-R" in command
    assert command[command.index("-R") + 1] == "10,20,300,400"


def test_build_region_arg_formats_tuple() -> None:
    """``_build_region_arg`` joins the tuple as ``x,y,w,h``."""
    # Arrange / Act
    arg = screenshot._build_region_arg((1, 2, 3, 4))

    # Assert
    assert arg == "1,2,3,4"


# --------------------------------------------------------------------------- #
# Fallback to mss
# --------------------------------------------------------------------------- #
def test_non_zero_exit_triggers_mss_fallback(patched_fs: dict[str, MagicMock]) -> None:
    """A non-zero screencapture exit falls back to mss and returns its bytes."""
    # Arrange
    fake_mss = _make_mss(FAKE_MSS_PNG)
    with (
        patch.object(screenshot.subprocess, "run", return_value=_completed(1)),
        patch.dict("sys.modules", {"mss": fake_mss, "mss.tools": fake_mss.tools}),
    ):
        # Act
        result = screenshot.grab_screen()

    # Assert
    assert base64.b64decode(result) == FAKE_MSS_PNG
    fake_mss.tools.to_png.assert_called_once_with(b"raw-rgb", (1920, 1080))


def test_screencapture_missing_triggers_mss_fallback(patched_fs: dict[str, MagicMock]) -> None:
    """If the ``screencapture`` binary is missing, mss is used instead."""
    # Arrange
    fake_mss = _make_mss(FAKE_MSS_PNG)
    with (
        patch.object(screenshot.subprocess, "run", side_effect=FileNotFoundError("no screencapture")),
        patch.dict("sys.modules", {"mss": fake_mss, "mss.tools": fake_mss.tools}),
    ):
        # Act
        result = screenshot.grab_screen()

    # Assert
    assert base64.b64decode(result) == FAKE_MSS_PNG


def test_empty_native_png_triggers_mss_fallback(patched_fs: dict[str, MagicMock]) -> None:
    """An empty native PNG (OSError) falls back to mss."""
    # Arrange
    patched_fs["read_bytes"].return_value = b""
    fake_mss = _make_mss(FAKE_MSS_PNG)
    with (
        patch.object(screenshot.subprocess, "run", return_value=_completed(0)),
        patch.dict("sys.modules", {"mss": fake_mss, "mss.tools": fake_mss.tools}),
    ):
        # Act
        result = screenshot.grab_screen()

    # Assert
    assert base64.b64decode(result) == FAKE_MSS_PNG


def test_mss_fallback_uses_region_rectangle(patched_fs: dict[str, MagicMock]) -> None:
    """The mss fallback grabs the requested region rectangle, not a monitor."""
    # Arrange
    region = (5, 6, 7, 8)
    fake_mss = _make_mss(FAKE_MSS_PNG)
    sct = fake_mss.mss.return_value.__enter__.return_value
    with (
        patch.object(screenshot.subprocess, "run", side_effect=OSError("boom")),
        patch.dict("sys.modules", {"mss": fake_mss, "mss.tools": fake_mss.tools}),
    ):
        # Act
        screenshot.grab_screen(region=region)

    # Assert
    sct.grab.assert_called_once_with({"left": 5, "top": 6, "width": 7, "height": 8})


def test_mss_fallback_uses_full_monitor_without_region(patched_fs: dict[str, MagicMock]) -> None:
    """Without a region the mss fallback grabs the virtual ``monitors[0]`` box."""
    # Arrange
    fake_mss = _make_mss(FAKE_MSS_PNG)
    sct = fake_mss.mss.return_value.__enter__.return_value
    with (
        patch.object(screenshot.subprocess, "run", side_effect=OSError("boom")),
        patch.dict("sys.modules", {"mss": fake_mss, "mss.tools": fake_mss.tools}),
    ):
        # Act
        screenshot.grab_screen()

    # Assert
    sct.grab.assert_called_once_with(sct.monitors[0])


def test_mss_failure_raises_runtime_error(patched_fs: dict[str, MagicMock]) -> None:
    """If mss yields no PNG bytes, a RuntimeError is raised."""
    # Arrange
    fake_mss = _make_mss(b"")
    with (
        patch.object(screenshot.subprocess, "run", side_effect=OSError("boom")),
        patch.dict("sys.modules", {"mss": fake_mss, "mss.tools": fake_mss.tools}),
    ):
        # Act / Assert
        with pytest.raises(RuntimeError, match="mss failed to encode"):
            screenshot.grab_screen()


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_png_bytes_to_base64_is_ascii_str() -> None:
    """``_png_bytes_to_base64`` returns an ASCII string that round-trips."""
    # Arrange / Act
    encoded = screenshot._png_bytes_to_base64(FAKE_NATIVE_PNG)

    # Assert
    assert isinstance(encoded, str)
    assert base64.b64decode(encoded) == FAKE_NATIVE_PNG
