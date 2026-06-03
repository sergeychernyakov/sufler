# tests/audio/test_devices.py

"""Unit tests for :mod:`src.audio.devices`.

These tests never touch real audio hardware: the ``sounddevice`` backend is
replaced via ``sys.modules`` with a stub whose ``query_devices`` returns a fixed
mix of input-capable and output-only devices. They follow the
Arrange -> Act -> Assert pattern and cover input-device filtering plus every
branch of :func:`resolve_input_device` — ``None``/empty, valid and invalid
integer indices, case-insensitive name substring matching, and unknown names.
"""

import sys
from types import SimpleNamespace
from typing import Dict, Iterator, List
from unittest.mock import patch

import pytest

from src.audio.devices import list_input_devices, resolve_input_device

#: A representative device table: two input devices (indices 0, 2) interleaved
#: with output-only devices (indices 1, 3). Mirrors ``sounddevice``'s schema.
FAKE_DEVICES: List[Dict[str, object]] = [
    {"name": "MacBook Pro Microphone", "max_input_channels": 1, "max_output_channels": 0},
    {"name": "MacBook Pro Speakers", "max_input_channels": 0, "max_output_channels": 2},
    {"name": "BlackHole 2ch", "max_input_channels": 2, "max_output_channels": 2},
    {"name": "External Headphones", "max_input_channels": 0, "max_output_channels": 2},
]


def _fake_sounddevice(devices: List[Dict[str, object]]) -> SimpleNamespace:
    """Build a stub ``sounddevice`` module exposing only ``query_devices``.

    Args:
        devices (List[Dict[str, object]]): The device table to return.

    Returns:
        SimpleNamespace: An object usable in place of the ``sounddevice`` module.
    """
    return SimpleNamespace(query_devices=lambda: devices)


@pytest.fixture
def patched_sd() -> Iterator[None]:
    """Patch ``sounddevice`` in ``sys.modules`` with the fake device table.

    Yields:
        None: The fixture only installs the stub for the test's duration.
    """
    with patch.dict(sys.modules, {"sounddevice": _fake_sounddevice(FAKE_DEVICES)}):
        yield


# --------------------------------------------------------------------------- #
# list_input_devices
# --------------------------------------------------------------------------- #
def test_list_input_devices_keeps_only_input_capable(patched_sd: None) -> None:
    """Only devices with max_input_channels > 0 are returned, in order."""
    # Act
    inputs = list_input_devices()

    # Assert
    assert [entry["index"] for entry in inputs] == [0, 2]
    assert [entry["name"] for entry in inputs] == ["MacBook Pro Microphone", "BlackHole 2ch"]


def test_list_input_devices_entries_have_index_and_name(patched_sd: None) -> None:
    """Each returned entry exposes at least an int index and a str name."""
    # Act
    inputs = list_input_devices()

    # Assert
    for entry in inputs:
        assert isinstance(entry["index"], int)
        assert isinstance(entry["name"], str)


def test_list_input_devices_empty_when_no_inputs() -> None:
    """A table of output-only devices yields an empty input list."""
    # Arrange
    outputs_only = [{"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2}]

    # Act
    with patch.dict(sys.modules, {"sounddevice": _fake_sounddevice(outputs_only)}):
        inputs = list_input_devices()

    # Assert
    assert inputs == []


# --------------------------------------------------------------------------- #
# resolve_input_device — None / empty
# --------------------------------------------------------------------------- #
def test_resolve_none_returns_none() -> None:
    """``None`` resolves to ``None`` (caller uses the default input)."""
    # Act / Assert: no backend access is needed for the empty case.
    assert resolve_input_device(None) is None


def test_resolve_empty_string_returns_none() -> None:
    """An empty string resolves to ``None`` without querying devices."""
    # Act / Assert
    assert resolve_input_device("") is None


# --------------------------------------------------------------------------- #
# resolve_input_device — integer indices
# --------------------------------------------------------------------------- #
def test_resolve_valid_int_returns_same_index(patched_sd: None) -> None:
    """A valid input-device index resolves to itself."""
    # Act / Assert
    assert resolve_input_device(2) == 2


def test_resolve_output_only_int_raises(patched_sd: None) -> None:
    """An index pointing at an output-only device raises ValueError."""
    # Act / Assert: index 1 is the speakers (no input channels).
    with pytest.raises(ValueError, match="not a valid input device"):
        resolve_input_device(1)


def test_resolve_out_of_range_int_raises(patched_sd: None) -> None:
    """An index beyond the device table raises ValueError listing the inputs."""
    # Act / Assert
    with pytest.raises(ValueError, match="Available input devices"):
        resolve_input_device(99)


# --------------------------------------------------------------------------- #
# resolve_input_device — name substring matching
# --------------------------------------------------------------------------- #
def test_resolve_name_substring_case_insensitive(patched_sd: None) -> None:
    """A case-insensitive name substring resolves to the matching index."""
    # Act / Assert: "blackhole" matches "BlackHole 2ch" at index 2.
    assert resolve_input_device("blackhole") == 2


def test_resolve_name_substring_partial_match(patched_sd: None) -> None:
    """A partial substring of an input device name resolves correctly."""
    # Act / Assert: "Microphone" matches "MacBook Pro Microphone" at index 0.
    assert resolve_input_device("Microphone") == 0


def test_resolve_unknown_name_raises_listing_devices(patched_sd: None) -> None:
    """An unmatched name raises ValueError naming the available inputs."""
    # Act / Assert
    with pytest.raises(ValueError, match="No input device matching"):
        resolve_input_device("nonexistent device")


def test_resolve_name_does_not_match_output_only(patched_sd: None) -> None:
    """A name that only matches an output device is treated as unknown."""
    # Act / Assert: "Speakers" exists but is output-only, so no match.
    with pytest.raises(ValueError, match="No input device matching"):
        resolve_input_device("Speakers")


# --------------------------------------------------------------------------- #
# resolve_input_device — no input devices at all
# --------------------------------------------------------------------------- #
def test_resolve_int_with_no_inputs_reports_none_available() -> None:
    """With no input devices, an index error states none are available."""
    # Arrange
    outputs_only = [{"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2}]

    # Act / Assert
    with patch.dict(sys.modules, {"sounddevice": _fake_sounddevice(outputs_only)}):
        with pytest.raises(ValueError, match="No input devices available."):
            resolve_input_device(0)
