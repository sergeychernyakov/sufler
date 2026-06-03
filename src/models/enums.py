# src/models/enums.py

"""
Enumerations for various commission types, and other related categories.
"""

from enum import Enum


class YesNoEnum(str, Enum):
    """
    Enumeration for Yes/No answers.
    """

    YES = "YES"
    NO = "NO"


class Mode(str, Enum):
    """Suggestion style for the prompter's answer (see SUFLER_SPEC.md)."""

    ANSWER = "answer"  # краткий готовый ответ, 2–4 пункта телеграфно
    COACH = "coach"  # 3 тезиса-опоры, человек говорит сам


class SttEngine(str, Enum):
    """Available speech-to-text backends (Apple Silicon; see SUFLER_SPEC.md)."""

    MLX = "mlx"
    WHISPERCPP = "whispercpp"
    DEEPGRAM = "deepgram"
