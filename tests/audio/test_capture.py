# tests/audio/test_capture.py

"""Unit tests for :mod:`src.audio.capture`.

These tests never open a real microphone or a real stream. Segmentation is
driven directly through :meth:`MicrophoneCapture._ingest` with synthetic numpy
blocks (loud = ``np.full(n, 0.2)``, silence = ``np.zeros(n)``), and the
``sounddevice`` backend is patched via ``sys.modules`` so ``start`` / ``stop``
exercise a mocked ``InputStream``. They follow the Arrange -> Act -> Assert
pattern and cover leading-silence suppression, partial emission at
``partial_seconds`` boundaries, finalization on a pause, post-final reset and
the start/stop lifecycle.
"""

import sys
from typing import List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.audio.capture import MicrophoneCapture

SAMPLE_RATE = 16000


def _loud(num_samples: int) -> np.ndarray:
    """Build a voiced (loud) mono block of the given length.

    Args:
        num_samples (int): Number of samples in the block.

    Returns:
        np.ndarray: A ``float32`` block filled with ``0.2`` (RMS = 0.2).
    """
    return np.full(num_samples, 0.2, dtype=np.float32)


def _silence(num_samples: int) -> np.ndarray:
    """Build a silent mono block of the given length.

    Args:
        num_samples (int): Number of samples in the block.

    Returns:
        np.ndarray: A ``float32`` block of zeros (RMS = 0.0).
    """
    return np.zeros(num_samples, dtype=np.float32)


class _Recorder:
    """Collects utterances handed to a callback for later assertions."""

    def __init__(self) -> None:
        """Initializes an empty list of received utterances."""
        self.utterances: List[np.ndarray] = []

    def __call__(self, utterance: np.ndarray) -> None:
        """Records one utterance.

        Args:
            utterance (np.ndarray): The audio array passed by the capturer.
        """
        self.utterances.append(utterance)

    @property
    def count(self) -> int:
        """int: How many times the callback has been invoked."""
        return len(self.utterances)


@pytest.fixture
def callbacks() -> tuple[_Recorder, _Recorder]:
    """Provide fresh partial/final recorders.

    Returns:
        tuple[_Recorder, _Recorder]: The ``on_partial`` and ``on_final``
        recorders, in that order.
    """
    return _Recorder(), _Recorder()


def _make_capture(
    partial: _Recorder,
    final: _Recorder,
    *,
    partial_seconds: float = 1.2,
    silence_seconds: float = 0.7,
    silence_rms: float = 0.01,
) -> MicrophoneCapture:
    """Build a capturer wired to the given recorders.

    Args:
        partial (_Recorder): Recorder for ``on_partial``.
        final (_Recorder): Recorder for ``on_final``.
        partial_seconds (float): Partial-emission spacing in seconds.
        silence_seconds (float): Trailing silence needed to finalize.
        silence_rms (float): RMS silence threshold.

    Returns:
        MicrophoneCapture: A configured capturer at :data:`SAMPLE_RATE`.
    """
    return MicrophoneCapture(
        on_partial=partial,
        on_final=final,
        sample_rate=SAMPLE_RATE,
        partial_seconds=partial_seconds,
        silence_seconds=silence_seconds,
        silence_rms=silence_rms,
    )


# --------------------------------------------------------------------------- #
# Leading silence
# --------------------------------------------------------------------------- #
def test_leading_silence_produces_no_callbacks(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """Silence before any speech yields neither partials nor finals."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)

    # Act
    for _ in range(10):
        capture._ingest(_silence(SAMPLE_RATE))  # 10 s of silence

    # Assert
    assert on_partial.count == 0
    assert on_final.count == 0


def test_empty_block_is_ignored(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """An empty block triggers no callbacks and starts no utterance."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)

    # Act
    capture._ingest(np.empty(0, dtype=np.float32))

    # Assert
    assert on_partial.count == 0
    assert on_final.count == 0


# --------------------------------------------------------------------------- #
# Final on a pause
# --------------------------------------------------------------------------- #
def test_speech_then_silence_emits_single_final(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """Short speech followed by >= silence_seconds emits exactly one final."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)
    speech = _loud(SAMPLE_RATE // 2)  # 0.5 s of speech (< one partial window)
    silence = _silence(int(SAMPLE_RATE * 0.7))  # exactly silence_seconds

    # Act
    capture._ingest(speech)
    capture._ingest(silence)

    # Assert
    assert on_final.count == 1
    # The final utterance is the speech plus the trailing silence that closed it.
    assert on_final.utterances[0].shape[0] == speech.shape[0] + silence.shape[0]


def test_final_utterance_contains_the_voiced_audio(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """The finalized utterance carries the original voiced samples up front."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)
    speech = _loud(SAMPLE_RATE // 2)

    # Act
    capture._ingest(speech)
    capture._ingest(_silence(int(SAMPLE_RATE * 0.7)))

    # Assert
    np.testing.assert_array_equal(on_final.utterances[0][: speech.shape[0]], speech)


def test_silence_just_below_threshold_does_not_finalize(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """Trailing silence shorter than silence_seconds does not finalize."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)

    # Act
    capture._ingest(_loud(SAMPLE_RATE // 2))
    capture._ingest(_silence(int(SAMPLE_RATE * 0.6)))  # 0.6 s < 0.7 s

    # Assert
    assert on_final.count == 0


def test_brief_silence_then_more_speech_stays_one_utterance(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """A sub-threshold gap is absorbed; speech resumes the same utterance."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)

    # Act
    capture._ingest(_loud(SAMPLE_RATE // 2))  # speak
    capture._ingest(_silence(int(SAMPLE_RATE * 0.4)))  # brief gap (< 0.7 s)
    capture._ingest(_loud(SAMPLE_RATE // 2))  # resume speaking
    capture._ingest(_silence(int(SAMPLE_RATE * 0.7)))  # real pause -> finalize

    # Assert: only one utterance was finalized despite the internal gap.
    assert on_final.count == 1


# --------------------------------------------------------------------------- #
# Partials during continuous speech
# --------------------------------------------------------------------------- #
def test_long_speech_emits_partials_at_boundaries(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """~3.6 s of continuous speech emits one partial per partial_seconds."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)  # partial_seconds = 1.2

    # Act: feed 0.3 s blocks for 3.6 s total -> boundaries at 1.2 / 2.4 / 3.6 s.
    block = _loud(int(SAMPLE_RATE * 0.3))
    for _ in range(12):
        capture._ingest(block)

    # Assert
    assert on_partial.count == 3
    assert on_final.count == 0  # still speaking; nothing finalized


def test_partials_grow_monotonically(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """Each successive partial carries at least as much audio as the prior."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)

    # Act
    block = _loud(int(SAMPLE_RATE * 0.3))
    for _ in range(12):
        capture._ingest(block)

    # Assert
    lengths = [u.shape[0] for u in on_partial.utterances]
    assert lengths == sorted(lengths)
    assert lengths[0] >= int(SAMPLE_RATE * 1.2)


def test_single_large_block_flushes_multiple_partials(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """One block spanning several windows flushes a partial per crossed mark."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)  # 1.2 s windows

    # Act: a single 3.0 s voiced block crosses the 1.2 s and 2.4 s marks.
    capture._ingest(_loud(int(SAMPLE_RATE * 3.0)))

    # Assert
    assert on_partial.count == 2


def test_trailing_silence_does_not_emit_partial(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """Buffered trailing silence never crosses a partial boundary on its own."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)

    # Act: 0.5 s voiced (below the 1.2 s mark) then 1.0 s of silence. The total
    # buffered audio exceeds 1.2 s, but only voiced audio may trigger a partial.
    capture._ingest(_loud(SAMPLE_RATE // 2))
    capture._ingest(_silence(SAMPLE_RATE))

    # Assert
    assert on_partial.count == 0
    assert on_final.count == 1


def test_partial_then_final_on_pause(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """Speech long enough for a partial, then a pause, yields a partial + final."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)

    # Act
    capture._ingest(_loud(int(SAMPLE_RATE * 1.5)))  # crosses one 1.2 s boundary
    capture._ingest(_silence(int(SAMPLE_RATE * 0.7)))  # pause -> finalize

    # Assert
    assert on_partial.count == 1
    assert on_final.count == 1


# --------------------------------------------------------------------------- #
# Reset after a final
# --------------------------------------------------------------------------- #
def test_state_resets_for_next_utterance(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """After a final, a second utterance segments independently of the first."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)

    # Act: first utterance (no partial: 0.5 s), pause, then second utterance.
    capture._ingest(_loud(SAMPLE_RATE // 2))
    capture._ingest(_silence(int(SAMPLE_RATE * 0.7)))
    capture._ingest(_loud(SAMPLE_RATE // 2))
    capture._ingest(_silence(int(SAMPLE_RATE * 0.7)))

    # Assert: two independent finals, no partials (each utterance < 1.2 s voiced).
    assert on_final.count == 2
    assert on_partial.count == 0


def test_internal_buffers_cleared_after_final(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """Finalization empties the buffer and zeroes all per-utterance counters."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)

    # Act
    capture._ingest(_loud(int(SAMPLE_RATE * 1.5)))
    capture._ingest(_silence(int(SAMPLE_RATE * 0.7)))

    # Assert
    assert capture._buffer == []
    assert capture._voiced_samples == 0
    assert capture._trailing_silence == 0
    assert capture._partials_emitted == 0


def test_leading_silence_after_reset_is_ignored(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """Silence following a final does not open a spurious second utterance."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)

    # Act
    capture._ingest(_loud(SAMPLE_RATE // 2))
    capture._ingest(_silence(int(SAMPLE_RATE * 0.7)))  # finalize utterance #1
    capture._ingest(_silence(SAMPLE_RATE))  # 1 s more silence -> ignored

    # Assert
    assert on_final.count == 1
    assert capture._buffer == []


# --------------------------------------------------------------------------- #
# RMS silence threshold
# --------------------------------------------------------------------------- #
def test_amplitude_above_threshold_counts_as_speech(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """A block with RMS above silence_rms opens and sustains an utterance."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final, silence_rms=0.01)
    quiet_voice = np.full(SAMPLE_RATE // 2, 0.02, dtype=np.float32)  # RMS 0.02 > 0.01

    # Act
    capture._ingest(quiet_voice)
    capture._ingest(_silence(int(SAMPLE_RATE * 0.7)))

    # Assert
    assert on_final.count == 1


def test_amplitude_at_threshold_counts_as_silence(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """A block whose RMS equals silence_rms is treated as silence (no start)."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final, silence_rms=0.01)
    at_threshold = np.full(SAMPLE_RATE, 0.01, dtype=np.float32)  # RMS == 0.01

    # Act
    capture._ingest(at_threshold)

    # Assert: leading "silence" is ignored, so no utterance is opened.
    assert on_partial.count == 0
    assert on_final.count == 0
    assert capture._buffer == []


# --------------------------------------------------------------------------- #
# Utterance assembly helper
# --------------------------------------------------------------------------- #
def test_current_utterance_is_empty_when_nothing_buffered(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """With no buffered audio, _current_utterance returns an empty float32 array."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)

    # Act
    utterance = capture._current_utterance()

    # Assert
    assert utterance.shape == (0,)
    assert utterance.dtype == np.float32


# --------------------------------------------------------------------------- #
# Input-level reporting
# --------------------------------------------------------------------------- #
def test_ingest_reports_block_peak_level(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """Each non-empty block reports its peak amplitude through ``on_level``."""
    # Arrange
    on_partial, on_final = callbacks
    levels: List[float] = []
    capture = MicrophoneCapture(
        on_partial=on_partial, on_final=on_final, on_level=levels.append, sample_rate=SAMPLE_RATE
    )

    # Act
    capture._ingest(_loud(100))  # constant 0.2 -> peak 0.2

    # Assert
    assert levels == [pytest.approx(0.2, abs=1e-6)]


# --------------------------------------------------------------------------- #
# Stream lifecycle (mocked sounddevice)
# --------------------------------------------------------------------------- #
def test_start_opens_mocked_input_stream(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """start() constructs and starts a sounddevice InputStream, mono float32."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)
    fake_sd = MagicMock()
    stream = fake_sd.InputStream.return_value

    # Act
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        capture.start()

    # Assert
    fake_sd.InputStream.assert_called_once()
    kwargs = fake_sd.InputStream.call_args.kwargs
    assert kwargs["samplerate"] == SAMPLE_RATE
    assert kwargs["channels"] == 1
    assert kwargs["dtype"] == "float32"
    assert kwargs["callback"] == capture._stream_callback
    stream.start.assert_called_once()
    assert capture._stream is stream


def test_start_defaults_device_to_none(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """Without a device, start() opens the stream on the default input (None)."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)
    fake_sd = MagicMock()

    # Act
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        capture.start()

    # Assert
    assert fake_sd.InputStream.call_args.kwargs["device"] is None


def test_start_forwards_device_to_input_stream(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """A configured device is passed through to sounddevice.InputStream."""
    # Arrange
    on_partial, on_final = callbacks
    capture = MicrophoneCapture(
        on_partial=on_partial,
        on_final=on_final,
        sample_rate=SAMPLE_RATE,
        device="BlackHole 2ch",
    )
    fake_sd = MagicMock()

    # Act
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        capture.start()

    # Assert
    assert fake_sd.InputStream.call_args.kwargs["device"] == "BlackHole 2ch"


def test_start_forwards_integer_device_index(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """An integer device index is forwarded verbatim to InputStream."""
    # Arrange
    on_partial, on_final = callbacks
    capture = MicrophoneCapture(
        on_partial=on_partial,
        on_final=on_final,
        sample_rate=SAMPLE_RATE,
        device=2,
    )
    fake_sd = MagicMock()

    # Act
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        capture.start()

    # Assert
    assert fake_sd.InputStream.call_args.kwargs["device"] == 2


def test_stop_stops_and_closes_the_stream(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """stop() stops, closes and clears a running stream."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)
    fake_sd = MagicMock()
    stream = fake_sd.InputStream.return_value
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        capture.start()

        # Act
        capture.stop()

    # Assert
    stream.stop.assert_called_once()
    stream.close.assert_called_once()
    assert capture._stream is None


def test_stop_without_start_is_noop(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """Calling stop() before start() does nothing and stays safe."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)

    # Act / Assert (no exception)
    capture.stop()
    assert capture._stream is None


# --------------------------------------------------------------------------- #
# Stream callback bridges to _ingest
# --------------------------------------------------------------------------- #
def test_stream_callback_forwards_block_to_ingest(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """The sounddevice callback flattens (frames, 1) input and calls _ingest."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)
    indata = _loud(SAMPLE_RATE // 2).reshape(-1, 1)  # (frames, 1) like sounddevice

    # Act
    with patch.object(capture, "_ingest") as ingest:
        capture._stream_callback(indata, indata.shape[0], None, None)

    # Assert
    ingest.assert_called_once()
    forwarded = ingest.call_args.args[0]
    assert forwarded.ndim == 1
    assert forwarded.shape[0] == indata.shape[0]


def test_stream_callback_logs_status_and_still_ingests(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """A truthy stream status is logged but does not stop the block ingest."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)
    indata = _loud(SAMPLE_RATE // 4).reshape(-1, 1)

    # Act
    with patch.object(capture, "_ingest") as ingest, patch("src.audio.capture.logger") as log:
        capture._stream_callback(indata, indata.shape[0], None, "input overflow")

    # Assert
    log.warning.assert_called_once()
    ingest.assert_called_once()


def test_stream_callback_drives_real_segmentation(callbacks: tuple[_Recorder, _Recorder]) -> None:
    """End-to-end: callback-fed speech then silence yields one final."""
    # Arrange
    on_partial, on_final = callbacks
    capture = _make_capture(on_partial, on_final)

    # Act: route blocks through the real callback (no mocked _ingest).
    speech = _loud(SAMPLE_RATE // 2).reshape(-1, 1)
    silence = _silence(int(SAMPLE_RATE * 0.7)).reshape(-1, 1)
    capture._stream_callback(speech, speech.shape[0], None, None)
    capture._stream_callback(silence, silence.shape[0], None, None)

    # Assert
    assert on_final.count == 1
