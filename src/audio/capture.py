# src/audio/capture.py

"""Low-latency microphone capture with partial/final utterance segmentation.

For a live interview prompter, latency is critical: a fixed 2-4 s buffer is too
slow. This module captures the microphone as **mono float32 @ 16 kHz** and
segments the stream into utterances on the fly:

* **Fast partials** - while the user keeps speaking, the growing utterance audio
  is emitted roughly every ``partial_seconds`` (default 1.2 s) so a downstream
  pipeline can draft-transcribe it immediately.
* **Final on pause** - once trailing silence reaches ``silence_seconds``
  (default 0.7 s) and speech has been buffered, the full utterance is emitted
  and the internal buffer resets for the next one.

The module performs **no transcription**. It only emits raw audio (numpy
``float32`` arrays) through the ``on_partial`` / ``on_final`` callbacks; a
separate pipeline feeds those arrays to a speech-to-text engine.

Silence is detected per audio block via root-mean-square (RMS) amplitude:
blocks whose RMS falls below ``silence_rms`` are treated as silence. Leading
silence is ignored - an utterance does not start until voiced audio arrives.

Testability:
    All segmentation lives in the pure :meth:`MicrophoneCapture._ingest` method,
    which takes a block of samples and drives the callbacks. The sounddevice
    stream callback merely forwards blocks to it, so tests can exercise every
    segmentation path with synthetic numpy blocks and never touch a real
    microphone. The ``sounddevice`` backend is imported lazily inside
    :meth:`MicrophoneCapture.start`.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Union

import numpy as np

from src.helpers.logger import get_logger

logger = get_logger(__name__)


class MicrophoneCapture:  # pylint: disable=too-many-instance-attributes
    """Captures the microphone and segments it into partial/final utterances.

    Voiced samples are accumulated into the current utterance. Trailing silence
    is tracked by RMS; each time the accumulated audio crosses a
    ``partial_seconds`` boundary an ``on_partial`` callback fires with the
    growing utterance, and once trailing silence reaches ``silence_seconds`` an
    ``on_final`` callback fires with the complete utterance before the buffer
    resets.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        on_partial: Callable[[np.ndarray], None],
        on_final: Callable[[np.ndarray], None],
        sample_rate: int = 16000,
        partial_seconds: float = 1.2,
        silence_seconds: float = 0.7,
        silence_rms: float = 0.01,
        max_utterance_seconds: float = 8.0,
        device: Optional[Union[int, str]] = None,
    ) -> None:
        """Configures the capturer and its segmentation thresholds.

        Args:
            on_partial (Callable[[np.ndarray], None]): Called with the growing
                utterance (mono float32) at roughly each ``partial_seconds``
                boundary while the user is still speaking.
            on_final (Callable[[np.ndarray], None]): Called once with the
                complete utterance (mono float32) when trailing silence reaches
                ``silence_seconds`` and speech has been buffered.
            sample_rate (int): Capture sample rate in Hz. Defaults to ``16000``.
            partial_seconds (float): Spacing, in seconds of accumulated audio,
                between successive ``on_partial`` emissions. Defaults to ``1.2``.
            silence_seconds (float): Trailing silence required to finalize an
                utterance, in seconds. Defaults to ``0.7``.
            silence_rms (float): RMS amplitude at or below which an audio block
                is treated as silence. Defaults to ``0.01``.
            device (Optional[Union[int, str]]): The sounddevice input device to
                capture from — an index or name passed straight to
                ``sounddevice.InputStream(device=...)``. ``None`` (the default)
                uses the system default input. Resolve names/indices up front
                with :func:`src.audio.devices.resolve_input_device`.
        """
        self._on_partial = on_partial
        self._on_final = on_final
        self.sample_rate = sample_rate
        self.partial_seconds = partial_seconds
        self.silence_seconds = silence_seconds
        self.silence_rms = silence_rms

        #: Input device passed to ``sounddevice.InputStream``; ``None`` = default.
        self._device = device

        #: Samples that constitute one ``partial_seconds`` window.
        self._partial_samples = max(1, int(round(partial_seconds * sample_rate)))
        #: Samples that constitute the ``silence_seconds`` finalize window.
        self._silence_samples = max(1, int(round(silence_seconds * sample_rate)))
        #: Hard cap on utterance length; forces a finalize so the buffer can't grow unbounded.
        self._max_utterance_samples = max(1, int(round(max_utterance_seconds * sample_rate)))

        #: Voiced (plus interspersed) samples buffered for the current utterance.
        self._buffer: list[np.ndarray] = []
        #: Total samples buffered this utterance (drives the hard length cap).
        self._total_samples = 0
        #: Voiced samples seen so far this utterance; drives partial boundaries.
        self._voiced_samples = 0
        #: Consecutive trailing silence samples since the last voiced block.
        self._trailing_silence = 0
        #: Number of ``on_partial`` boundaries already emitted this utterance.
        self._partials_emitted = 0

        #: The live sounddevice ``InputStream`` while capturing, else ``None``.
        self._stream: Optional[Any] = None

    def start(self) -> None:
        """Opens the sounddevice input stream and begins capturing.

        ``sounddevice`` is imported lazily here so merely importing this module
        (for example, in tests) never touches the audio backend. The stream is
        opened as mono float32 at :attr:`sample_rate` on the configured input
        device (the system default when unset); its callback forwards each
        captured block to :meth:`_ingest`.
        """
        import sounddevice as sd  # pylint: disable=import-outside-toplevel

        stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self._device,
            callback=self._stream_callback,
        )
        stream.start()
        self._stream = stream
        logger.info(
            "Microphone capture started (%d Hz, mono float32, device=%s)",
            self.sample_rate,
            self._device if self._device is not None else "default",
        )

    def stop(self) -> None:
        """Stops and closes the input stream if one is running.

        Any speech still buffered is left unflushed; finalization only happens
        on a detected pause. Calling :meth:`stop` when not started is a no-op.
        """
        stream = self._stream
        if stream is not None:
            stream.stop()
            stream.close()
            self._stream = None
            logger.info("Microphone capture stopped")

    def _stream_callback(
        self,
        indata: np.ndarray,
        frames: int,  # pylint: disable=unused-argument
        time_info: Any,  # pylint: disable=unused-argument
        status: Any,
    ) -> None:
        """Forwards a captured audio block from sounddevice to :meth:`_ingest`.

        This runs on sounddevice's high-priority audio thread, so it stays
        minimal: it logs any stream status, flattens the ``(frames, 1)`` block
        to a 1-D mono array and hands it to the segmentation logic.

        Args:
            indata (np.ndarray): Captured block shaped ``(frames, channels)``.
            frames (int): Number of frames in the block (unused; inferred from
                ``indata``).
            time_info (Any): Sounddevice timing info (unused).
            status (Any): Sounddevice ``CallbackFlags``; truthy on xruns.
        """
        if status:
            logger.warning("Microphone stream status: %s", status)
        # ``indata`` is a reused buffer — COPY it (np.array), or buffered blocks get
        # overwritten by later callbacks before transcription and decode to silence.
        self._ingest(np.array(indata, dtype=np.float32).reshape(-1))

    def _ingest(self, block: np.ndarray) -> None:
        """Segments a block of mono samples, emitting partials and finals.

        This is the pure heart of the module and is what tests drive directly.
        The block is classified as voiced or silent by RMS. Leading silence is
        ignored. Once speech has started, every sample (including short internal
        gaps) is buffered into the current utterance; ``on_partial`` fires each
        time the accumulated *voiced* audio crosses a ``partial_seconds``
        boundary, and ``on_final`` fires when trailing silence reaches
        ``silence_seconds``.

        Args:
            block (np.ndarray): A 1-D mono ``float32`` block of samples. Empty
                blocks are ignored.
        """
        samples = np.asarray(block, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return

        is_silent = self._is_silent(samples)

        # Ignore leading silence: do not open an utterance until speech arrives.
        if not self._buffer and is_silent:
            return

        self._buffer.append(samples)
        self._total_samples += samples.size
        if is_silent:
            self._trailing_silence += samples.size
        else:
            self._trailing_silence = 0
            self._voiced_samples += samples.size
            self._emit_due_partials()

        if self._trailing_silence >= self._silence_samples or self._total_samples >= self._max_utterance_samples:
            self._finalize()

    def _is_silent(self, samples: np.ndarray) -> bool:
        """Reports whether a block is silence based on its RMS amplitude.

        Args:
            samples (np.ndarray): A 1-D ``float32`` block of samples.

        Returns:
            bool: ``True`` if the block's RMS is at or below
            :attr:`silence_rms`, otherwise ``False``.
        """
        rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
        return rms <= self.silence_rms

    def _emit_due_partials(self) -> None:
        """Emits ``on_partial`` for every newly crossed ``partial_seconds`` mark.

        The number of boundaries crossed is derived from the accumulated
        *voiced* sample count, so a single large voiced block can trigger more
        than one pending partial while trailing silence never does. Each partial
        receives the full utterance buffered so far.
        """
        boundaries = self._voiced_samples // self._partial_samples
        while self._partials_emitted < boundaries:
            self._partials_emitted += 1
            self._on_partial(self._current_utterance())

    def _finalize(self) -> None:
        """Emits ``on_final`` with the complete utterance and resets state."""
        utterance = self._current_utterance()
        self._reset()
        self._on_final(utterance)

    def _current_utterance(self) -> np.ndarray:
        """Concatenates the buffered blocks into one contiguous utterance.

        Returns:
            np.ndarray: The buffered audio as a single 1-D ``float32`` array, or
            an empty ``float32`` array when nothing is buffered.
        """
        if not self._buffer:
            return np.empty(0, dtype=np.float32)
        return np.concatenate(self._buffer)

    def _reset(self) -> None:
        """Clears all per-utterance buffers and counters."""
        self._buffer = []
        self._total_samples = 0
        self._voiced_samples = 0
        self._trailing_silence = 0
        self._partials_emitted = 0
