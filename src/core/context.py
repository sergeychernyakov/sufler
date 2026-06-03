# src/core/context.py

"""Rolling conversation context for the sufler prompter (Phase 6).

This module keeps a small, time-bounded slice of the live interview so that
follow-up questions (e.g. ``"а чем отличается от предыдущего варианта?"``) can be
answered with the right history. It deliberately holds:

* a *sliding window* of recently recognized speech (last ``window_seconds``),
* the last confidently recognized question,
* the last manually captured screenshot (base64).

The block produced by :meth:`RollingContext.render` is meant to be prepended to a
Claude request alongside the current prompt.

The component is pure logic: it performs no I/O and pulls in no heavy
dependencies. Time is injectable everywhere via an optional ``now`` argument
(defaulting to :func:`time.monotonic`) so behaviour is fully deterministic under
test.
"""

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional

from src.helpers.logger import get_logger

logger = get_logger(__name__)

# Default length of the speech retention window, in seconds. The spec calls for
# roughly the last 30-60 seconds of recognized speech; 45s sits in the middle.
DEFAULT_WINDOW_SECONDS: float = 45.0


@dataclass(frozen=True)
class SpeechSegment:
    """A single recognized speech fragment stamped with its arrival time.

    Attributes:
        text: The recognized speech text (already stripped, never empty).
        timestamp: Monotonic time, in seconds, at which the fragment was added.
    """

    text: str
    timestamp: float


class RollingContext:
    """A time-bounded, sliding window of recent interview context.

    The context tracks recent speech, the last recognized question and the last
    screenshot. Speech fragments older than ``window_seconds`` relative to the
    current time are evicted lazily whenever the window is read or rendered.

    The instance is not thread-safe; callers that share it across threads must
    provide their own synchronization.
    """

    def __init__(self, window_seconds: float = DEFAULT_WINDOW_SECONDS) -> None:
        """Initializes an empty rolling context.

        Args:
            window_seconds: Retention horizon for speech fragments, in seconds.
                Must be strictly positive.

        Raises:
            ValueError: If ``window_seconds`` is not strictly positive.
        """
        if window_seconds <= 0:
            raise ValueError("window_seconds must be strictly positive")
        self._window_seconds: float = float(window_seconds)
        self._speech: Deque[SpeechSegment] = deque()
        self._last_question: Optional[str] = None
        self._screenshot_b64: Optional[str] = None

    @property
    def window_seconds(self) -> float:
        """Returns the speech retention horizon, in seconds."""
        return self._window_seconds

    @staticmethod
    def _resolve_now(now: Optional[float]) -> float:
        """Returns ``now`` if provided, otherwise the current monotonic time."""
        return time.monotonic() if now is None else now

    def add_speech(self, text: str, *, now: Optional[float] = None) -> None:
        """Appends a recognized speech fragment to the sliding window.

        Blank or whitespace-only fragments are ignored. Adding a fragment also
        evicts any entries that have fallen outside the retention window.

        Args:
            text: The recognized speech text. Leading/trailing whitespace is
                stripped; empty results are discarded.
            now: Optional monotonic timestamp (seconds) for the fragment.
                Defaults to :func:`time.monotonic`.
        """
        cleaned = text.strip()
        if not cleaned:
            logger.debug("Ignoring blank speech fragment")
            return
        current = self._resolve_now(now)
        self._speech.append(SpeechSegment(text=cleaned, timestamp=current))
        self._evict_expired(current)

    def set_question(self, text: str) -> None:
        """Records the last confidently recognized question.

        Args:
            text: The question text. Leading/trailing whitespace is stripped;
                a blank value clears the stored question.
        """
        cleaned = text.strip()
        self._last_question = cleaned or None

    def set_screenshot(self, image_b64: Optional[str]) -> None:
        """Stores (or clears) the last manual screenshot as base64.

        Args:
            image_b64: Base64-encoded image payload, or ``None`` to clear it.
                An empty string is also treated as "no screenshot".
        """
        self._screenshot_b64 = image_b64 or None

    def last_question(self) -> Optional[str]:
        """Returns the last recognized question, or ``None`` if unset."""
        return self._last_question

    def last_screenshot(self) -> Optional[str]:
        """Returns the last stored screenshot (base64), or ``None`` if unset."""
        return self._screenshot_b64

    def recent_speech(self, *, now: Optional[float] = None) -> str:
        """Returns the in-window speech as a single newline-joined string.

        Fragments older than ``window_seconds`` relative to ``now`` are evicted
        before the result is built, so the return value only reflects the live
        window.

        Args:
            now: Optional monotonic timestamp (seconds) used as "the present".
                Defaults to :func:`time.monotonic`.

        Returns:
            The retained speech fragments joined by newlines, oldest first; an
            empty string when nothing is in the window.
        """
        segments = self._live_segments(now)
        return "\n".join(segment.text for segment in segments)

    def render(self, *, now: Optional[float] = None) -> str:
        """Renders a compact, labeled context block for a Claude request.

        The block contains the recent speech window and the last recognized
        question, each under a terse label, and omits any section that is empty.
        The screenshot is intentionally excluded: it is sent to Claude as a
        separate image part, not inlined into this text block.

        Args:
            now: Optional monotonic timestamp (seconds) used as "the present".
                Defaults to :func:`time.monotonic`.

        Returns:
            A newline-separated block, or an empty string when there is no
            in-window speech and no recorded question.
        """
        sections: List[str] = []
        speech = self.recent_speech(now=now)
        if speech:
            sections.append(f"Recent speech:\n{speech}")
        if self._last_question:
            sections.append(f"Last question: {self._last_question}")
        return "\n\n".join(sections)

    def clear(self) -> None:
        """Resets all state: speech window, last question and screenshot."""
        self._speech.clear()
        self._last_question = None
        self._screenshot_b64 = None

    def _live_segments(self, now: Optional[float]) -> List[SpeechSegment]:
        """Evicts expired fragments and returns the survivors, oldest first."""
        current = self._resolve_now(now)
        self._evict_expired(current)
        return list(self._speech)

    def _evict_expired(self, current: float) -> None:
        """Drops speech fragments whose age exceeds the retention window.

        A fragment is kept while ``current - timestamp <= window_seconds`` so
        that an entry exactly at the window edge is retained; the deque is
        ordered by arrival time, so eviction stops at the first live fragment.
        """
        cutoff = current - self._window_seconds
        while self._speech and self._speech[0].timestamp < cutoff:
            self._speech.popleft()
