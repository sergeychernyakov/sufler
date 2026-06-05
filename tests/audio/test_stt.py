# tests/audio/test_stt.py

"""Unit tests for :mod:`src.audio.stt`.

The heavy native dependency ``mlx_whisper`` is **not** installed in the test
environment and is never imported at module top. Tests that exercise the MLX
path inject a fake module via ``patch.dict("sys.modules", {"mlx_whisper": ...})``
so the lazy ``import mlx_whisper`` inside ``MlxWhisperEngine.transcribe`` resolves
to the stub. They follow the Arrange -> Act -> Assert pattern and cover:

* ``create_engine`` returning the right class per :class:`SttEngine` value, its
  string alias, and the ``config.stt_engine`` default;
* unknown engines raising ``ValueError`` and the reserved ``whispercpp`` engine
  raising ``NotImplementedError``;
* ``MlxWhisperEngine.transcribe`` mapping a mocked result into a ``Transcript``
  and passing the configured model through;
* a missing ``mlx_whisper`` raising a clear ``RuntimeError``;
* ``DeepgramEngine.transcribe`` raising ``NotImplementedError``.
"""

from types import ModuleType
from typing import Any, Dict, Iterator, List
from unittest.mock import patch

import numpy as np
import pytest

from src.audio import stt
from src.audio.stt import (
    DEFAULT_MLX_MODEL,
    DeepgramEngine,
    MlxWhisperEngine,
    STTEngine,
    Transcript,
    _is_hallucination,
    create_engine,
)
from src.models.enums import SttEngine


def _fake_audio() -> np.ndarray:
    """Build a tiny mono ``float32`` PCM array for transcription calls.

    Returns:
        np.ndarray: A short ramp of ``float32`` samples in ``[-1.0, 1.0]``.
    """
    return np.linspace(-0.5, 0.5, num=16, dtype=np.float32)


class _FakeMlxWhisper(ModuleType):
    """Stand-in for the ``mlx_whisper`` module exposing a recording ``transcribe``."""

    def __init__(self, result: Dict[str, Any]) -> None:
        """Store the canned result and prepare slots to capture call arguments.

        Args:
            result (Dict[str, Any]): The dict ``transcribe`` should return.
        """
        super().__init__("mlx_whisper")
        self._result = result
        self.calls: List[Dict[str, Any]] = []

    def transcribe(self, audio: Any, **kwargs: Any) -> Dict[str, Any]:
        """Record the call and return the canned result.

        Args:
            audio (Any): The audio passed by the engine.
            **kwargs (Any): Keyword arguments (notably ``path_or_hf_repo``).

        Returns:
            Dict[str, Any]: The pre-seeded fake transcription result.
        """
        self.calls.append({"audio": audio, "kwargs": kwargs})
        return self._result


@pytest.fixture
def fake_mlx() -> Iterator[_FakeMlxWhisper]:
    """Install a fake ``mlx_whisper`` module for the duration of a test.

    Yields:
        _FakeMlxWhisper: The injected fake module, pre-seeded with a Russian
        result, so tests can assert on its recorded calls.
    """
    fake = _FakeMlxWhisper({"text": "  привет мир  ", "language": "ru"})
    # Also stub model resolution so transcribe never hits Hugging Face in tests.
    with (
        patch.dict("sys.modules", {"mlx_whisper": fake}),
        patch.object(MlxWhisperEngine, "_model_path", lambda self: self.model),
    ):
        yield fake


# --------------------------------------------------------------------------- #
# create_engine: backend selection
# --------------------------------------------------------------------------- #
def test_create_engine_returns_mlx_for_enum() -> None:
    """``SttEngine.MLX`` builds an ``MlxWhisperEngine``."""
    # Act
    engine = create_engine(SttEngine.MLX)

    # Assert
    assert isinstance(engine, MlxWhisperEngine)


def test_create_engine_returns_deepgram_for_enum() -> None:
    """``SttEngine.DEEPGRAM`` builds a ``DeepgramEngine``."""
    # Act
    engine = create_engine(SttEngine.DEEPGRAM)

    # Assert
    assert isinstance(engine, DeepgramEngine)


def test_create_engine_accepts_string_alias() -> None:
    """A raw string value (``"mlx"``) selects the matching engine."""
    # Act
    engine = create_engine("mlx")

    # Assert
    assert isinstance(engine, MlxWhisperEngine)


def test_create_engine_default_comes_from_config() -> None:
    """With no argument, the engine type follows ``config.stt_engine``."""
    # Arrange
    from src.config import config

    expected = {
        SttEngine.MLX.value: MlxWhisperEngine,
        SttEngine.DEEPGRAM.value: DeepgramEngine,
    }[config.stt_engine]

    # Act
    engine = create_engine()

    # Assert
    assert isinstance(engine, expected)


def test_create_engine_default_is_mlx_when_config_is_mlx(monkeypatch: pytest.MonkeyPatch) -> None:
    """When config selects ``mlx`` (the project default) an MLX engine is built."""
    # Arrange: pin config to the documented default regardless of the env.
    monkeypatch.setattr(stt.config, "stt_engine", SttEngine.MLX.value)

    # Act
    engine = create_engine()

    # Assert
    assert isinstance(engine, MlxWhisperEngine)


def test_create_engine_returns_base_class_instances() -> None:
    """Every built engine is an ``STTEngine`` subclass instance."""
    # Act / Assert
    assert isinstance(create_engine(SttEngine.MLX), STTEngine)
    assert isinstance(create_engine(SttEngine.DEEPGRAM), STTEngine)


def test_create_engine_forwards_model_kwarg() -> None:
    """Extra kwargs (``model=``) are forwarded to the engine constructor."""
    # Act
    engine = create_engine(SttEngine.MLX, model="mlx-community/whisper-tiny")

    # Assert
    assert isinstance(engine, MlxWhisperEngine)
    assert engine.model == "mlx-community/whisper-tiny"


def test_create_engine_unknown_string_raises_value_error() -> None:
    """An unrecognised engine name raises ``ValueError`` listing valid options."""
    # Act / Assert
    with pytest.raises(ValueError, match="Unknown STT engine"):
        create_engine("does-not-exist")


def test_create_engine_whispercpp_not_implemented() -> None:
    """The reserved ``whispercpp`` engine raises ``NotImplementedError``."""
    # Act / Assert
    with pytest.raises(NotImplementedError, match="whispercpp"):
        create_engine(SttEngine.WHISPERCPP)


# --------------------------------------------------------------------------- #
# MlxWhisperEngine
# --------------------------------------------------------------------------- #
def test_mlx_default_model_constant() -> None:
    """The default model constant points at a turbo multilingual Whisper repo."""
    # Assert
    assert DEFAULT_MLX_MODEL == "mlx-community/whisper-large-v3-turbo"
    assert MlxWhisperEngine().model == DEFAULT_MLX_MODEL


def test_mlx_transcribe_maps_result_to_transcript(fake_mlx: _FakeMlxWhisper) -> None:
    """A mocked ``mlx_whisper.transcribe`` result becomes a ``Transcript``."""
    # Arrange
    engine = MlxWhisperEngine()

    # Act
    transcript = engine.transcribe(_fake_audio())

    # Assert
    assert isinstance(transcript, Transcript)
    assert transcript.text == "привет мир"  # whitespace is stripped
    assert transcript.language == "ru"


def test_mlx_transcribe_passes_model_through(fake_mlx: _FakeMlxWhisper) -> None:
    """The configured model is forwarded as ``path_or_hf_repo`` and audio passed."""
    # Arrange
    audio = _fake_audio()
    engine = MlxWhisperEngine(model="mlx-community/whisper-small")

    # Act
    engine.transcribe(audio)

    # Assert
    assert len(fake_mlx.calls) == 1
    call = fake_mlx.calls[0]
    assert call["kwargs"]["path_or_hf_repo"] == "mlx-community/whisper-small"
    # The engine peak-normalizes before transcribing, so it passes a (same-length) copy.
    assert call["audio"].size == audio.size


def test_mlx_transcribe_handles_missing_language(fake_mlx: _FakeMlxWhisper) -> None:
    """A result without a ``language`` key yields ``Transcript.language = None``."""
    # Arrange
    fake_mlx._result = {"text": "hello"}  # pylint: disable=protected-access
    engine = MlxWhisperEngine()

    # Act
    transcript = engine.transcribe(_fake_audio())

    # Assert
    assert transcript.text == "hello"
    assert transcript.language is None


def test_mlx_transcribe_handles_empty_result(fake_mlx: _FakeMlxWhisper) -> None:
    """An empty result dict yields an empty-text transcript, not an error."""
    # Arrange
    fake_mlx._result = {}  # pylint: disable=protected-access
    engine = MlxWhisperEngine()

    # Act
    transcript = engine.transcribe(_fake_audio())

    # Assert
    assert transcript.text == ""
    assert transcript.language is None


def test_mlx_transcribe_missing_dependency_raises_runtime_error() -> None:
    """When ``mlx_whisper`` cannot be imported, a clear ``RuntimeError`` is raised."""
    # Arrange: force the lazy ``import mlx_whisper`` to fail.
    engine = MlxWhisperEngine()
    with patch.dict("sys.modules", {"mlx_whisper": None}):
        # Act / Assert
        with pytest.raises(RuntimeError, match="pip install mlx-whisper"):
            engine.transcribe(_fake_audio())


# --------------------------------------------------------------------------- #
# DeepgramEngine
# --------------------------------------------------------------------------- #
def test_deepgram_transcribe_raises_not_implemented() -> None:
    """The Deepgram stub raises ``NotImplementedError`` until implemented."""
    # Arrange
    engine = DeepgramEngine()

    # Act / Assert
    with pytest.raises(NotImplementedError, match="Deepgram"):
        engine.transcribe(_fake_audio())


# --------------------------------------------------------------------------- #
# create_engine — model from config (SUFLER_STT_MODEL)
# --------------------------------------------------------------------------- #
def test_create_engine_mlx_uses_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """``config.stt_model`` is passed to the MLX engine when set."""
    # Arrange
    monkeypatch.setattr(stt.config, "stt_model", "mlx-community/whisper-small")

    # Act
    engine = create_engine(SttEngine.MLX)

    # Assert
    assert isinstance(engine, MlxWhisperEngine)
    assert engine.model == "mlx-community/whisper-small"


def test_create_engine_explicit_model_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit ``model=`` kwarg wins over ``config.stt_model``."""
    # Arrange
    monkeypatch.setattr(stt.config, "stt_model", "mlx-community/whisper-small")

    # Act
    engine = create_engine(SttEngine.MLX, model="custom/model")

    # Assert
    assert isinstance(engine, MlxWhisperEngine)
    assert engine.model == "custom/model"


def test_create_engine_mlx_falls_back_to_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``config.stt_model`` empty, the engine keeps its built-in default."""
    # Arrange
    monkeypatch.setattr(stt.config, "stt_model", "")

    # Act
    engine = create_engine(SttEngine.MLX)

    # Assert
    assert isinstance(engine, MlxWhisperEngine)
    assert engine.model == DEFAULT_MLX_MODEL


# --------------------------------------------------------------------------- #
# Language selection (SUFLER_STT_LANGUAGE)
# --------------------------------------------------------------------------- #
def test_mlx_transcribe_passes_language(fake_mlx: _FakeMlxWhisper) -> None:
    """A pinned language is forwarded to ``mlx_whisper.transcribe``."""
    # Arrange
    engine = MlxWhisperEngine(language="ru")

    # Act
    engine.transcribe(_fake_audio())

    # Assert
    assert fake_mlx.calls[0]["kwargs"]["language"] == "ru"


def test_mlx_transcribe_language_defaults_to_auto(fake_mlx: _FakeMlxWhisper) -> None:
    """With no language, transcribe passes ``language=None`` (Whisper auto-detects)."""
    # Arrange
    engine = MlxWhisperEngine()

    # Act
    engine.transcribe(_fake_audio())

    # Assert
    assert fake_mlx.calls[0]["kwargs"]["language"] is None


def test_create_engine_mlx_uses_configured_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """``config.stt_language`` is passed to the MLX engine when set."""
    # Arrange
    monkeypatch.setattr(stt.config, "stt_language", "en")

    # Act
    engine = create_engine(SttEngine.MLX)

    # Assert
    assert isinstance(engine, MlxWhisperEngine)
    assert engine.language == "en"


def test_create_engine_explicit_language_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit ``language=`` kwarg wins over ``config.stt_language``."""
    # Arrange
    monkeypatch.setattr(stt.config, "stt_language", "en")

    # Act
    engine = create_engine(SttEngine.MLX, language="ru")

    # Assert
    assert isinstance(engine, MlxWhisperEngine)
    assert engine.language == "ru"


def test_create_engine_mlx_language_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``config.stt_language`` empty, the engine auto-detects (language ``None``)."""
    # Arrange
    monkeypatch.setattr(stt.config, "stt_language", "")

    # Act
    engine = create_engine(SttEngine.MLX)

    # Assert
    assert isinstance(engine, MlxWhisperEngine)
    assert engine.language is None


# --------------------------------------------------------------------------- #
# Hallucination filtering (silence artefacts)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Субтитры сделал DimaTorzok", True),
        ("Субтитры создавал DimaTorzok", True),
        ("Субтитры подогнал «Симон»", True),
        ("Продолжение следует...", True),
        ("Спасибо за просмотр!", True),
        ("You", True),
        ("Thank you.", True),
        ("расскажи про индексы в postgres", False),
        ("привет мир", False),
        ("спасибо", False),
        ("", False),
    ],
)
def test_is_hallucination(text: str, expected: bool) -> None:
    """Known silence artefacts are flagged; real speech is not."""
    assert _is_hallucination(text) is expected


def test_mlx_transcribe_discards_subtitle_hallucination(fake_mlx: _FakeMlxWhisper) -> None:
    """The 'Субтитры сделал DimaTorzok' silence hallucination is discarded."""
    # Arrange
    fake_mlx._result = {"text": "Субтитры сделал DimaTorzok", "language": "ru"}  # pylint: disable=protected-access
    engine = MlxWhisperEngine()

    # Act / Assert
    assert engine.transcribe(_fake_audio()).text == ""


def test_mlx_transcribe_discards_english_silence_filler(fake_mlx: _FakeMlxWhisper) -> None:
    """A bare 'You' (classic English silence hallucination) is discarded."""
    # Arrange
    fake_mlx._result = {"text": "You", "language": "en"}  # pylint: disable=protected-access
    engine = MlxWhisperEngine()

    # Act / Assert
    assert engine.transcribe(_fake_audio()).text == ""


def test_mlx_transcribe_discards_disallowed_language(
    fake_mlx: _FakeMlxWhisper, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transcript in a language outside the allowlist (e.g. nl) is discarded."""
    # Arrange
    monkeypatch.setattr(stt.config, "stt_allowed_langs", "ru,en")
    fake_mlx._result = {"text": "welk een driet", "language": "nl"}  # pylint: disable=protected-access
    engine = MlxWhisperEngine()

    # Act / Assert
    assert engine.transcribe(_fake_audio()).text == ""


def test_mlx_transcribe_keeps_allowed_language(fake_mlx: _FakeMlxWhisper, monkeypatch: pytest.MonkeyPatch) -> None:
    """A transcript in an allowed language passes the language filter."""
    # Arrange
    monkeypatch.setattr(stt.config, "stt_allowed_langs", "ru,en")
    fake_mlx._result = {"text": "привет мир", "language": "ru"}  # pylint: disable=protected-access
    engine = MlxWhisperEngine()

    # Act / Assert
    assert engine.transcribe(_fake_audio()).text == "привет мир"


def test_is_degenerate_catches_repeated_sentences() -> None:
    """A looped short phrase (silence hallucination) is flagged as degenerate."""
    from src.audio.stt import _is_degenerate  # pylint: disable=import-outside-toplevel

    assert _is_degenerate("Thank you. Thank you. Thank you.") is True
    assert _is_degenerate("Are you injured? Thank you. Thank you. Thank you.") is True
    assert _is_degenerate("Что такое REST? Это архитектурный стиль.") is False


def test_quiet_clip_below_rms_gate_is_skipped(fake_mlx: _FakeMlxWhisper, monkeypatch: pytest.MonkeyPatch) -> None:
    """A clip with RMS below ``config.min_speech_rms`` is skipped before the model runs."""
    # Arrange: a near-silent clip and a high gate.
    monkeypatch.setattr(stt.config, "min_speech_rms", 0.1)
    engine = MlxWhisperEngine()
    quiet = np.full(16, 0.001, dtype=np.float32)  # rms 0.001 < 0.1

    # Act / Assert: empty result, and the model was never called.
    assert engine.transcribe(quiet).text == ""
    assert fake_mlx.calls == []
