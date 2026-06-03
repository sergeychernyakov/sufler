# tests/audio/test_pipeline.py

"""Tests for the SpeechPipeline (capture -> engine -> text), no real audio/model."""

from unittest.mock import MagicMock

import numpy as np

from src.audio.pipeline import SpeechPipeline
from src.audio.stt import Transcript


class _FakeCapture:
    """Records the handlers the pipeline wires in and start/stop calls."""

    def __init__(self, *, on_partial, on_final, sample_rate=16000) -> None:
        self.on_partial = on_partial
        self.on_final = on_final
        self.sample_rate = sample_rate
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


def test_partial_audio_forwards_draft_text() -> None:
    _, capture, _, partials, _ = _make(text="драфт")
    capture.on_partial(_audio())
    assert partials == ["драфт"]


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


def test_start_stop_delegate_to_capture() -> None:
    pipeline, capture, _, _, _ = _make()
    pipeline.start()
    pipeline.stop()
    assert capture.started == 1
    assert capture.stopped == 1
