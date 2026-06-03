# tests/core/test_context.py

"""Unit tests for :mod:`src.core.context`.

These tests drive time through the injectable ``now`` argument so the sliding
window behaviour is fully deterministic and never touches the wall clock.
"""

import pytest

from src.core.context import DEFAULT_WINDOW_SECONDS, RollingContext, SpeechSegment


class TestConstruction:
    """Construction and basic invariants of :class:`RollingContext`."""

    def test_default_window_is_45_seconds(self) -> None:
        # Arrange / Act
        context = RollingContext()

        # Assert
        assert context.window_seconds == 45.0
        assert DEFAULT_WINDOW_SECONDS == 45.0

    def test_custom_window_is_stored_as_float(self) -> None:
        # Arrange / Act
        context = RollingContext(window_seconds=10)

        # Assert
        assert context.window_seconds == 10.0
        assert isinstance(context.window_seconds, float)

    @pytest.mark.parametrize("bad_window", [0, -1, -0.5])
    def test_non_positive_window_raises(self, bad_window: float) -> None:
        # Act / Assert
        with pytest.raises(ValueError, match="strictly positive"):
            RollingContext(window_seconds=bad_window)

    def test_empty_context_reads_are_empty(self) -> None:
        # Arrange
        context = RollingContext()

        # Act / Assert
        assert context.recent_speech(now=0.0) == ""
        assert context.render(now=0.0) == ""
        assert context.last_question() is None
        assert context.last_screenshot() is None


class TestAddSpeech:
    """Behaviour of :meth:`RollingContext.add_speech` and the speech window."""

    def test_add_speech_is_returned_by_recent_speech(self) -> None:
        # Arrange
        context = RollingContext(window_seconds=30.0)

        # Act
        context.add_speech("hello world", now=0.0)

        # Assert
        assert context.recent_speech(now=0.0) == "hello world"

    def test_multiple_fragments_join_oldest_first_with_newlines(self) -> None:
        # Arrange
        context = RollingContext(window_seconds=60.0)

        # Act
        context.add_speech("first", now=0.0)
        context.add_speech("second", now=1.0)
        context.add_speech("third", now=2.0)

        # Assert
        assert context.recent_speech(now=2.0) == "first\nsecond\nthird"

    def test_speech_is_stripped(self) -> None:
        # Arrange
        context = RollingContext()

        # Act
        context.add_speech("  padded  ", now=0.0)

        # Assert
        assert context.recent_speech(now=0.0) == "padded"

    @pytest.mark.parametrize("blank", ["", "   ", "\n", "\t  \n"])
    def test_blank_speech_is_ignored(self, blank: str) -> None:
        # Arrange
        context = RollingContext()

        # Act
        context.add_speech(blank, now=0.0)

        # Assert
        assert context.recent_speech(now=0.0) == ""

    def test_add_speech_defaults_now_to_monotonic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Arrange: pin time.monotonic so the default path is deterministic.
        monkeypatch.setattr("src.core.context.time.monotonic", lambda: 100.0)
        context = RollingContext(window_seconds=5.0)

        # Act
        context.add_speech("auto-stamped")

        # Assert: read with an explicit now within the window.
        assert context.recent_speech(now=102.0) == "auto-stamped"
        # And it is evicted once now moves past the window edge.
        assert context.recent_speech(now=106.0) == ""


class TestEviction:
    """Sliding-window eviction driven via the injectable ``now`` parameter."""

    def test_fragment_older_than_window_is_evicted_from_recent_speech(self) -> None:
        # Arrange
        context = RollingContext(window_seconds=45.0)
        context.add_speech("stale", now=0.0)

        # Act: advance time just past the 45s window.
        result = context.recent_speech(now=45.1)

        # Assert
        assert result == ""

    def test_fragment_at_exact_window_edge_is_retained(self) -> None:
        # Arrange
        context = RollingContext(window_seconds=45.0)
        context.add_speech("edge", now=0.0)

        # Act: age == window_seconds exactly -> kept (inclusive edge).
        result = context.recent_speech(now=45.0)

        # Assert
        assert result == "edge"

    def test_only_stale_fragments_are_dropped(self) -> None:
        # Arrange
        context = RollingContext(window_seconds=30.0)
        context.add_speech("oldest", now=0.0)
        context.add_speech("middle", now=10.0)
        context.add_speech("newest", now=25.0)

        # Act: at now=31.0 the cutoff is 1.0, so "oldest" (t=0) is dropped.
        result = context.recent_speech(now=31.0)

        # Assert
        assert result == "middle\nnewest"

    def test_all_fragments_evicted_when_far_in_future(self) -> None:
        # Arrange
        context = RollingContext(window_seconds=15.0)
        context.add_speech("a", now=0.0)
        context.add_speech("b", now=5.0)
        context.add_speech("c", now=10.0)

        # Act
        result = context.recent_speech(now=1000.0)

        # Assert
        assert result == ""

    def test_adding_new_fragment_evicts_stale_ones(self) -> None:
        # Arrange
        context = RollingContext(window_seconds=20.0)
        context.add_speech("stale", now=0.0)

        # Act: a new fragment 21s later should push the stale one out at write time.
        context.add_speech("fresh", now=21.0)

        # Assert: reading at the same instant shows only the fresh fragment.
        assert context.recent_speech(now=21.0) == "fresh"

    def test_eviction_is_persistent_across_reads(self) -> None:
        # Arrange
        context = RollingContext(window_seconds=10.0)
        context.add_speech("gone", now=0.0)

        # Act: a future read evicts the fragment...
        assert context.recent_speech(now=100.0) == ""
        # ...and a subsequent earlier read does not resurrect it.
        result = context.recent_speech(now=5.0)

        # Assert
        assert result == ""


class TestQuestion:
    """Behaviour of :meth:`set_question` / :meth:`last_question`."""

    def test_set_and_get_question(self) -> None:
        # Arrange
        context = RollingContext()

        # Act
        context.set_question("What is a closure?")

        # Assert
        assert context.last_question() == "What is a closure?"

    def test_question_is_stripped(self) -> None:
        # Arrange
        context = RollingContext()

        # Act
        context.set_question("  trimmed?  ")

        # Assert
        assert context.last_question() == "trimmed?"

    def test_setting_question_overwrites_previous(self) -> None:
        # Arrange
        context = RollingContext()
        context.set_question("first?")

        # Act
        context.set_question("second?")

        # Assert
        assert context.last_question() == "second?"

    @pytest.mark.parametrize("blank", ["", "   ", "\n"])
    def test_blank_question_clears_it(self, blank: str) -> None:
        # Arrange
        context = RollingContext()
        context.set_question("real?")

        # Act
        context.set_question(blank)

        # Assert
        assert context.last_question() is None


class TestScreenshot:
    """Behaviour of :meth:`set_screenshot` / :meth:`last_screenshot`."""

    def test_set_and_get_screenshot(self) -> None:
        # Arrange
        context = RollingContext()

        # Act
        context.set_screenshot("YWJjZA==")

        # Assert
        assert context.last_screenshot() == "YWJjZA=="

    def test_none_clears_screenshot(self) -> None:
        # Arrange
        context = RollingContext()
        context.set_screenshot("YWJjZA==")

        # Act
        context.set_screenshot(None)

        # Assert
        assert context.last_screenshot() is None

    def test_empty_string_is_treated_as_no_screenshot(self) -> None:
        # Arrange
        context = RollingContext()
        context.set_screenshot("YWJjZA==")

        # Act
        context.set_screenshot("")

        # Assert
        assert context.last_screenshot() is None


class TestRender:
    """Behaviour of :meth:`RollingContext.render`."""

    def test_render_includes_recent_speech_and_last_question(self) -> None:
        # Arrange
        context = RollingContext(window_seconds=60.0)
        context.add_speech("we discussed hashing", now=0.0)
        context.add_speech("then sorting", now=5.0)
        context.set_question("how does it differ from the previous one?")

        # Act
        block = context.render(now=5.0)

        # Assert
        assert "Recent speech:" in block
        assert "we discussed hashing" in block
        assert "then sorting" in block
        assert "Last question: how does it differ from the previous one?" in block

    def test_render_omits_evicted_speech(self) -> None:
        # Arrange
        context = RollingContext(window_seconds=30.0)
        context.add_speech("stale fragment", now=0.0)
        context.add_speech("fresh fragment", now=20.0)

        # Act: cutoff at now=31.0 is 1.0, so the t=0 fragment is gone.
        block = context.render(now=31.0)

        # Assert
        assert "stale fragment" not in block
        assert "fresh fragment" in block

    def test_render_with_only_speech(self) -> None:
        # Arrange
        context = RollingContext()
        context.add_speech("only speech", now=0.0)

        # Act
        block = context.render(now=0.0)

        # Assert
        assert block == "Recent speech:\nonly speech"
        assert "Last question" not in block

    def test_render_with_only_question(self) -> None:
        # Arrange
        context = RollingContext()
        context.set_question("only a question?")

        # Act
        block = context.render(now=0.0)

        # Assert
        assert block == "Last question: only a question?"
        assert "Recent speech" not in block

    def test_render_empty_when_speech_evicted_and_no_question(self) -> None:
        # Arrange
        context = RollingContext(window_seconds=10.0)
        context.add_speech("will expire", now=0.0)

        # Act
        block = context.render(now=100.0)

        # Assert
        assert block == ""

    def test_render_excludes_screenshot(self) -> None:
        # Arrange: screenshot must not leak into the text block.
        context = RollingContext()
        context.set_screenshot("c2hvdWxkLW5vdC1hcHBlYXI=")
        context.add_speech("spoken", now=0.0)

        # Act
        block = context.render(now=0.0)

        # Assert
        assert "c2hvdWxkLW5vdC1hcHBlYXI=" not in block
        assert "spoken" in block

    def test_render_sections_separated_by_blank_line(self) -> None:
        # Arrange
        context = RollingContext()
        context.add_speech("line", now=0.0)
        context.set_question("q?")

        # Act
        block = context.render(now=0.0)

        # Assert
        assert block == "Recent speech:\nline\n\nLast question: q?"


class TestClear:
    """Behaviour of :meth:`RollingContext.clear`."""

    def test_clear_resets_all_state(self) -> None:
        # Arrange
        context = RollingContext()
        context.add_speech("something", now=0.0)
        context.set_question("a question?")
        context.set_screenshot("YWJjZA==")

        # Act
        context.clear()

        # Assert
        assert context.recent_speech(now=0.0) == ""
        assert context.render(now=0.0) == ""
        assert context.last_question() is None
        assert context.last_screenshot() is None

    def test_context_is_reusable_after_clear(self) -> None:
        # Arrange
        context = RollingContext(window_seconds=30.0)
        context.add_speech("old", now=0.0)
        context.clear()

        # Act
        context.add_speech("new", now=1.0)

        # Assert
        assert context.recent_speech(now=1.0) == "new"


class TestDefaultNowPaths:
    """Covers the default (monotonic) time path of the read/render methods."""

    def test_recent_speech_and_render_default_now(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Arrange: freeze monotonic so the default-now branch is deterministic.
        monkeypatch.setattr("src.core.context.time.monotonic", lambda: 50.0)
        context = RollingContext(window_seconds=10.0)
        context.add_speech("within window", now=45.0)

        # Act / Assert: read with default now (=50.0); 45.0 is within 10s.
        assert context.recent_speech() == "within window"
        assert "within window" in context.render()


class TestSpeechSegment:
    """Sanity checks for the immutable :class:`SpeechSegment` value object."""

    def test_segment_fields(self) -> None:
        # Arrange / Act
        segment = SpeechSegment(text="hi", timestamp=1.5)

        # Assert
        assert segment.text == "hi"
        assert segment.timestamp == 1.5

    def test_segment_is_frozen(self) -> None:
        # Arrange
        segment = SpeechSegment(text="hi", timestamp=1.5)

        # Act / Assert
        with pytest.raises((AttributeError, TypeError)):
            segment.text = "mutated"  # type: ignore[misc]
