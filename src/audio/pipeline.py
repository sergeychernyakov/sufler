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
from typing import Callable, Optional

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
        """
        self._engine = engine
        self._on_partial_text = on_partial_text
        self._on_final_text = on_final_text
        self._sample_rate = sample_rate
        self._runner: Runner = runner or self._spawn_thread
        self._capture = capture_factory(
            on_partial=self._handle_partial_audio,
            on_final=self._handle_final_audio,
            sample_rate=sample_rate,
        )

    def start(self) -> None:
        """Starts listening to the microphone."""
        self._capture.start()

    def stop(self) -> None:
        """Stops listening to the microphone."""
        self._capture.stop()

    def _handle_partial_audio(self, audio: np.ndarray) -> None:
        """Transcribes a partial (in-progress) utterance off the audio thread."""
        self._runner(lambda: self._transcribe(audio, self._on_partial_text))

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
