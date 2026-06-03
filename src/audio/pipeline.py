# src/audio/pipeline.py

"""Speech pipeline: microphone capture → STT engine → partial/final text callbacks.

:class:`~src.audio.capture.MicrophoneCapture` emits raw audio segments; this pipeline
transcribes each one on a worker thread (transcription is slow) and forwards the
recognised text. Routing that text into the overlay / rolling context is the
controller's job, so the text callbacks are expected to be thread-safe (e.g. Qt
signal ``emit``).
"""

from __future__ import annotations

import threading
from typing import Callable, Optional, Union

import numpy as np

from src.audio.capture import MicrophoneCapture
from src.audio.stt import STTEngine
from src.helpers.logger import get_logger

logger = get_logger(__name__)

TextSink = Callable[[str], None]
Runner = Callable[[Callable[[], None]], None]
CaptureFactory = Callable[..., MicrophoneCapture]


class SpeechPipeline:
    """Wires microphone capture to an STT engine and forwards recognised text."""

    def __init__(
        self,
        engine: STTEngine,
        *,
        on_partial_text: TextSink,
        on_final_text: TextSink,
        capture_factory: CaptureFactory = MicrophoneCapture,
        runner: Optional[Runner] = None,
        sample_rate: int = 16000,
        device: Optional[Union[int, str]] = None,
    ) -> None:
        """Builds the pipeline and its capture (does not start listening).

        Args:
            engine (STTEngine): The speech-to-text engine.
            on_partial_text (TextSink): Called with draft text for in-progress speech.
            on_final_text (TextSink): Called with the finalised utterance text.
            capture_factory (CaptureFactory): Builds the capture (injectable for tests).
            runner (Optional[Runner]): Executes transcription work; defaults to a
                daemon thread. Tests inject a synchronous runner.
            sample_rate (int): Capture/transcription sample rate in Hz.
            device (Optional[Union[int, str]]): Input device index or name substring
                (e.g. ``"BlackHole"``) for loopback capture; ``None`` uses the default input.
        """
        self._engine = engine
        self._on_partial_text = on_partial_text
        self._on_final_text = on_final_text
        self._sample_rate = sample_rate
        self._runner: Runner = runner or self._spawn_thread
        self._listening = False
        self._capture = capture_factory(
            on_partial=self._handle_partial_audio,
            on_final=self._handle_final_audio,
            sample_rate=sample_rate,
            device=device,
        )

    def start(self) -> None:
        """Starts listening to the microphone (idempotent)."""
        if self._listening:
            return
        self._capture.start()
        self._listening = True

    def stop(self) -> None:
        """Stops listening to the microphone (idempotent)."""
        if not self._listening:
            return
        self._capture.stop()
        self._listening = False

    def set_listening(self, listening: bool) -> None:
        """Resumes or pauses live listening to match ``listening``.

        Pausing closes the input stream, so the operating-system microphone
        indicator turns off too — an honest "not listening" state.

        Args:
            listening (bool): ``True`` resumes microphone capture; ``False`` pauses it.
        """
        if listening:
            self.start()
        else:
            self.stop()

    @property
    def is_listening(self) -> bool:
        """Returns whether the microphone stream is currently open.

        Returns:
            bool: ``True`` while capturing, ``False`` when paused/stopped.
        """
        return self._listening

    def _handle_partial_audio(self, audio: np.ndarray) -> None:  # pylint: disable=unused-argument
        """Partials are intentionally not transcribed (finals only).

        Re-transcribing the growing utterance on every partial overloaded the engine;
        only finalized utterances are transcribed, which keeps recognition reliable.
        """

    def _handle_final_audio(self, audio: np.ndarray) -> None:
        """Transcribes a finalised utterance off the audio thread."""
        self._runner(lambda: self._transcribe(audio, self._on_final_text))

    def _transcribe(self, audio: np.ndarray, sink: TextSink) -> None:
        """Runs the engine and forwards non-empty text, swallowing engine errors."""
        try:
            transcript = self._engine.transcribe(audio, self._sample_rate)
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            logger.exception("Transcription failed")
            return
        text = transcript.text.strip()
        if text:
            sink(text)

    @staticmethod
    def _spawn_thread(work: Callable[[], None]) -> None:
        """Runs ``work`` on a daemon thread (default production runner)."""
        threading.Thread(target=work, daemon=True).start()
