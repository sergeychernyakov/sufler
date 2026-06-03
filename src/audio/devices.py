# src/audio/devices.py

"""Audio input-device enumeration and selector resolution (Phase 7 loopback).

For loopback capture the prompter must be able to record from a *chosen* input
device — typically the **BlackHole** virtual device that carries the
interviewer's voice — rather than only the system default microphone.

This module exposes two thin helpers over the ``sounddevice`` backend:

* :func:`list_input_devices` — every input-capable device as a plain ``dict``
  (``index`` + ``name``), so a UI or config screen can present the choices.
* :func:`resolve_input_device` — turn a loose selector (``None``, an integer
  index, or a name substring) into a concrete input-device index that
  :class:`src.audio.capture.MicrophoneCapture` can hand straight to
  ``sounddevice.InputStream(device=...)``.

``sounddevice`` is imported **lazily inside each function**, so merely importing
this module never requires PortAudio — importing it stays safe in tests and on
machines without the native backend.
"""

from __future__ import annotations

from typing import List, Optional, Union

from src.helpers.logger import get_logger

logger = get_logger(__name__)


def list_input_devices() -> List[dict]:
    """Lists the audio devices that can be used as a capture input.

    Queries the ``sounddevice`` backend and keeps only devices exposing at least
    one input channel (``max_input_channels > 0``); pure output devices (e.g.
    speakers) are dropped.

    Returns:
        List[dict]: One dict per input-capable device, in backend order. Each
        contains at least ``index`` (int, the PortAudio device index) and
        ``name`` (str, the human-readable device name).
    """
    import sounddevice as sd  # pylint: disable=import-outside-toplevel

    devices = sd.query_devices()
    inputs: List[dict] = []
    for index, device in enumerate(devices):
        if int(device.get("max_input_channels", 0)) > 0:
            inputs.append({"index": index, "name": str(device.get("name", ""))})

    logger.debug("Found %d input-capable audio device(s)", len(inputs))
    return inputs


def resolve_input_device(device: Optional[Union[int, str]]) -> Optional[int]:
    """Resolves a device selector to a concrete input-device index.

    Args:
        device (Optional[Union[int, str]]): The selector to resolve.

            * ``None`` or ``""`` — no explicit device; the caller should fall
              back to the system default input.
            * ``int`` — used verbatim if it names a valid input device.
            * ``str`` — matched case-insensitively against device names; the
              first input device whose name *contains* the string wins.

    Returns:
        Optional[int]: The resolved input-device index, or ``None`` when
        ``device`` is ``None``/empty (signalling "use the default input").

    Raises:
        ValueError: If an integer index is out of range or not input-capable,
            or if a name substring matches no input device.
    """
    if device is None or device == "":
        return None

    inputs = list_input_devices()

    if isinstance(device, int):
        if any(entry["index"] == device for entry in inputs):
            logger.info("Resolved input device index %d", device)
            return device
        raise ValueError(f"Device index {device} is not a valid input device. {_available(inputs)}")

    target = device.casefold()
    for entry in inputs:
        if target in str(entry["name"]).casefold():
            resolved = int(entry["index"])
            logger.info("Resolved input device %r to index %d (%s)", device, resolved, entry["name"])
            return resolved

    raise ValueError(f"No input device matching {device!r}. {_available(inputs)}")


def _available(inputs: List[dict]) -> str:
    """Renders the available input devices for an error message.

    Args:
        inputs (List[dict]): Input-device dicts as returned by
            :func:`list_input_devices`.

    Returns:
        str: A human-readable listing such as
        ``Available input devices: [0] MacBook Mic, [2] BlackHole 2ch`` or
        ``No input devices available.`` when the list is empty.
    """
    if not inputs:
        return "No input devices available."
    listing = ", ".join(f"[{entry['index']}] {entry['name']}" for entry in inputs)
    return f"Available input devices: {listing}"
