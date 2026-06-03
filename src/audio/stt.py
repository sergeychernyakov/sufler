# src/audio/stt.py

"""Swappable speech-to-text (STT) engines for the sufler prompter (Phase 5).

This module defines a small strategy/factory layer so the rest of the app can
transcribe microphone audio without caring which backend does the work. The
engine is selected in exactly one place — :func:`create_engine` — keyed by
:class:`src.models.enums.SttEngine`, so swapping backends is a one-line config
change (``SUFLER_STT_ENGINE``).

Engines:
    * :class:`MlxWhisperEngine` — the default. Runs Whisper natively on Apple
      Silicon via :mod:`mlx_whisper`. Language is auto-detected, which is what
      we want for Russian + English code-switching during interviews.
    * :class:`DeepgramEngine` — an interface-only stub. The streaming websocket
      implementation lands in a later phase.

All engines speak the same contract: take mono ``float32`` PCM audio as a NumPy
array and return a :class:`Transcript`. ``mlx_whisper`` is imported lazily
inside :meth:`MlxWhisperEngine.transcribe` so the app (and the test suite) run
fine on machines where the heavy native dependency is not installed.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from src.config import config
from src.helpers.logger import get_logger
from src.models.enums import SttEngine

logger = get_logger(__name__)

#: Default MLX Whisper model repository.
#:
#: ``large-v3-turbo`` is a distilled, multilingual Whisper checkpoint optimised
#: for low latency on Apple Silicon while keeping strong Russian + English
#: accuracy — a good fit for the code-switching heard in tech interviews. It is
#: overridable via the :class:`MlxWhisperEngine` constructor (or by passing
#: ``model=`` through :func:`create_engine`).
DEFAULT_MLX_MODEL: str = "mlx-community/whisper-large-v3-turbo"

#: Target sample rate (Hz) Whisper models expect for their input audio.
DEFAULT_SAMPLE_RATE: int = 16000


@dataclass
class Transcript:
    """The result of transcribing a chunk of audio.

    Attributes:
        text (str): The recognised text (may be empty for silence).
        language (Optional[str]): The detected language code (e.g. ``"ru"`` or
            ``"en"``) when the engine reports one; ``None`` otherwise.
    """

    text: str
    language: Optional[str] = None


class STTEngine(ABC):
    """Abstract base class for speech-to-text backends.

    Concrete engines convert mono ``float32`` PCM audio into a
    :class:`Transcript`, detecting the spoken language automatically so callers
    do not have to specify Russian vs. English up front.
    """

    @abstractmethod
    def transcribe(self, audio: np.ndarray, sample_rate: int = DEFAULT_SAMPLE_RATE) -> Transcript:
        """Transcribe mono ``float32`` PCM audio.

        Implementations auto-detect the language of the audio.

        Args:
            audio (np.ndarray): Mono ``float32`` PCM samples in ``[-1.0, 1.0]``.
            sample_rate (int): Sample rate of ``audio`` in Hz. Defaults to
                :data:`DEFAULT_SAMPLE_RATE` (16 kHz).

        Returns:
            Transcript: The recognised text and detected language.
        """
        raise NotImplementedError


class MlxWhisperEngine(STTEngine):
    """Default STT engine backed by MLX Whisper (native Apple Silicon).

    The :mod:`mlx_whisper` dependency is imported lazily inside
    :meth:`transcribe` so importing this module (and running the test suite)
    never requires the heavy native package to be installed.

    Attributes:
        model (str): The MLX Whisper model repo / local path used for inference.
    """

    def __init__(self, model: str = DEFAULT_MLX_MODEL) -> None:
        """Initialise the engine.

        Args:
            model (str): MLX Whisper Hugging Face repo id or local path.
                Defaults to :data:`DEFAULT_MLX_MODEL`.
        """
        self.model: str = model

    def transcribe(self, audio: np.ndarray, sample_rate: int = DEFAULT_SAMPLE_RATE) -> Transcript:
        """Transcribe audio with MLX Whisper, auto-detecting the language.

        Args:
            audio (np.ndarray): Mono ``float32`` PCM samples in ``[-1.0, 1.0]``.
            sample_rate (int): Sample rate of ``audio`` in Hz. Whisper resamples
                internally; the argument is accepted for interface symmetry and
                logged. Defaults to :data:`DEFAULT_SAMPLE_RATE`.

        Returns:
            Transcript: The recognised text and the detected language code.

        Raises:
            RuntimeError: If :mod:`mlx_whisper` is not installed.
        """
        try:
            import mlx_whisper  # pylint: disable=import-outside-toplevel
        except ImportError as exc:
            raise RuntimeError(
                "mlx_whisper is not installed. Install it with `pip install mlx-whisper` "
                "to use the default MLX Whisper STT engine on Apple Silicon."
            ) from exc

        logger.info(
            "Transcribing %d samples (sample_rate=%d Hz) with MLX Whisper model %s",
            int(audio.shape[0]) if audio.ndim else 0,
            sample_rate,
            self.model,
        )

        result: dict[str, Any] = mlx_whisper.transcribe(audio, path_or_hf_repo=self.model)
        text = str(result.get("text", "")).strip()
        language = result.get("language")
        logger.debug("MLX Whisper detected language=%s, text length=%d", language, len(text))
        return Transcript(text=text, language=language)


class DeepgramEngine(STTEngine):
    """Stub for a future Deepgram streaming STT engine.

    The interface is laid out now so :func:`create_engine` can already return it;
    the websocket-based streaming implementation arrives in a later phase.
    """

    def transcribe(self, audio: np.ndarray, sample_rate: int = DEFAULT_SAMPLE_RATE) -> Transcript:
        """Not implemented yet.

        Args:
            audio (np.ndarray): Mono ``float32`` PCM samples (unused).
            sample_rate (int): Sample rate in Hz (unused).

        Returns:
            Transcript: Never returns; always raises.

        Raises:
            NotImplementedError: Always — Deepgram STT lands in a later phase.
        """
        raise NotImplementedError("Deepgram streaming STT is not implemented yet (Phase: later).")


def create_engine(engine: SttEngine | str | None = None, **kwargs: Any) -> STTEngine:
    """Create an :class:`STTEngine` for the requested backend.

    This is the single place the backend is chosen, keyed by
    :class:`src.models.enums.SttEngine`. Swapping engines for the whole app is a
    one-value change (``engine`` argument or the ``SUFLER_STT_ENGINE`` env var
    behind ``config.stt_engine``).

    Args:
        engine (SttEngine | str | None): The backend to build. Accepts an
            :class:`SttEngine`, its string value (e.g. ``"mlx"``), or ``None`` to
            fall back to ``config.stt_engine``.
        **kwargs (Any): Extra keyword arguments forwarded to the engine
            constructor (e.g. ``model=`` for :class:`MlxWhisperEngine`).

    Returns:
        STTEngine: A ready-to-use engine instance.

    Raises:
        ValueError: If ``engine`` is not a recognised :class:`SttEngine` value.
        NotImplementedError: If a known-but-unbuilt engine (``whispercpp``) is
            requested.
    """
    if engine is None:
        engine = config.stt_engine

    try:
        selected = SttEngine(engine)
    except ValueError as exc:
        valid = ", ".join(member.value for member in SttEngine)
        raise ValueError(f"Unknown STT engine {engine!r}. Valid options are: {valid}.") from exc

    logger.info("Creating STT engine: %s", selected.value)

    if selected is SttEngine.MLX:
        return MlxWhisperEngine(**kwargs)
    if selected is SttEngine.DEEPGRAM:
        return DeepgramEngine(**kwargs)
    # SttEngine.WHISPERCPP — interface reserved, implementation lands later.
    raise NotImplementedError(f"STT engine {selected.value!r} is not implemented yet (Phase: later).")
