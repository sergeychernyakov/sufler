# tests/audio/test_pipeline.py

"""Tests for the SpeechPipeline (capture -> engine -> text), no real audio/model."""

from unittest.mock import MagicMock

import numpy as np

from src.audio.pipeline import SpeechPipeline
from src.audio.stt import Transcript


class _FakeCapture:
    """Records the handlers the pipeline wires in and start/stop calls."""

    def __init__(
        self,
        *,
        on_partial,
        on_final,
        on_level=None,
        sample_rate=16000,
        device=None,
        silence_seconds=0.45,
        max_utterance_seconds=5.0,
    ) -> None:
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_level = on_level
        self.sample_rate = sample_rate
        self.device = device
        self.silence_seconds = silence_seconds
        self.max_utterance_seconds = max_utterance_seconds
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


def _audio() -> np.ndarray:
    return np.zeros(16, dtype=np.float32)


def _make(text="привет мир", side_effect=None):
    engine = MagicMock()
    if side_effect is not None:
        engine.transcribe.side_effect = side_effect
    else:
        engine.transcribe.return_value = Transcript(text=text, language="ru")
    partials: list[str] = []
    finals: list[str] = []
    captures: dict[str, _FakeCapture] = {}

    def factory(**kwargs):
        capture = _FakeCapture(**kwargs)
        captures["capture"] = capture
        return capture

    pipeline = SpeechPipeline(
        engine,
        on_partial_text=partials.append,
        on_final_text=finals.append,
        capture_factory=factory,
        runner=lambda work: work(),  # synchronous
    )
    return pipeline, captures["capture"], engine, partials, finals


def test_final_audio_transcribes_and_forwards_text() -> None:
    _, capture, engine, _, finals = _make(text="что такое индекс")
    capture.on_final(_audio())
    assert finals == ["что такое индекс"]
    engine.transcribe.assert_called_once()


def test_partial_audio_is_not_transcribed() -> None:
    # Partials are intentionally ignored (only finals are transcribed) — re-transcribing
    # the growing utterance on every partial overloaded the engine.
    _, capture, engine, partials, _ = _make(text="драфт")
    capture.on_partial(_audio())
    assert partials == []
    engine.transcribe.assert_not_called()


def test_blank_transcript_is_not_forwarded() -> None:
    _, capture, _, partials, finals = _make(text="   ")
    capture.on_final(_audio())
    capture.on_partial(_audio())
    assert finals == []
    assert partials == []


def test_engine_error_is_swallowed() -> None:
    _, capture, _, _, finals = _make(side_effect=RuntimeError("model missing"))
    capture.on_final(_audio())  # must not raise
    assert finals == []


def test_overlapping_transcription_is_dropped() -> None:
    # A second utterance that arrives while the engine is busy must be dropped, never
    # transcribed concurrently (MLX/Metal is not thread-safe -> segfault).
    pipeline, capture, engine, _, finals = _make(text="привет")

    reentered: list[bool] = []

    def busy_transcribe(_audio_arg, _sr):
        # Simulate work in progress: try to run a second final from inside the first.
        got_lock = pipeline._transcribe_lock.acquire(blocking=False)  # noqa: SLF001
        reentered.append(got_lock)
        if got_lock:
            pipeline._transcribe_lock.release()  # noqa: SLF001
        from src.audio.stt import Transcript

        return Transcript(text="привет", language="ru")

    engine.transcribe.side_effect = busy_transcribe
    capture.on_final(_audio())

    # While _transcribe holds the lock, a re-entrant acquire must fail (lock held).
    assert reentered == [False]
    assert finals == ["привет"]


def test_start_stop_delegate_to_capture() -> None:
    pipeline, capture, _, _, _ = _make()
    pipeline.start()
    pipeline.stop()
    assert capture.started == 1
    assert capture.stopped == 1


def test_set_listening_starts_and_stops_idempotently() -> None:
    pipeline, capture, _, _, _ = _make()
    assert pipeline.is_listening is False

    pipeline.set_listening(True)
    pipeline.set_listening(True)  # idempotent: no second stream
    assert pipeline.is_listening is True
    assert capture.started == 1

    pipeline.set_listening(False)
    pipeline.set_listening(False)  # idempotent: no double stop
    assert pipeline.is_listening is False
    assert capture.stopped == 1


def test_on_level_is_forwarded_to_capture() -> None:
    captures: dict[str, _FakeCapture] = {}

    def factory(**kwargs):
        capture = _FakeCapture(**kwargs)
        captures["capture"] = capture
        return capture

    SpeechPipeline(
        MagicMock(),
        on_partial_text=lambda s: None,
        on_final_text=lambda s: None,
        on_level=lambda level: None,
        capture_factory=factory,
        runner=lambda work: work(),
    )

    assert captures["capture"].on_level is not None


def test_capture_timing_comes_from_config(monkeypatch) -> None:
    import src.audio.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod.config, "stt_silence_seconds", 0.3)
    monkeypatch.setattr(pipeline_mod.config, "stt_max_utterance_seconds", 4.0)
    captures: dict[str, _FakeCapture] = {}

    def factory(**kwargs):
        captures["capture"] = _FakeCapture(**kwargs)
        return captures["capture"]

    SpeechPipeline(
        MagicMock(),
        on_partial_text=lambda s: None,
        on_final_text=lambda s: None,
        capture_factory=factory,
        runner=lambda work: work(),
    )
    assert captures["capture"].silence_seconds == 0.3
    assert captures["capture"].max_utterance_seconds == 4.0


def test_device_is_forwarded_to_capture() -> None:
    captures: dict[str, _FakeCapture] = {}

    def factory(**kwargs):
        capture = _FakeCapture(**kwargs)
        captures["capture"] = capture
        return capture

    SpeechPipeline(
        MagicMock(),
        on_partial_text=lambda s: None,
        on_final_text=lambda s: None,
        capture_factory=factory,
        runner=lambda work: work(),
        device="BlackHole",
    )

    assert captures["capture"].device == "BlackHole"
