# src/config/settings.py

"""
Settings Module

This module defines configuration classes for different environments
(Development and Production) using dataclasses. It loads environment
variables from a `.env` file and sets various application settings.
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Base configuration class.

    Application settings are read from environment variables (``.env``); see
    ``.env.example`` for the full surface. Secrets such as the API key must
    never be hardcoded.
    """

    DEBUG: bool = False  # pylint: disable=invalid-name
    APP_ENV: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))  # pylint: disable=invalid-name

    # Anthropic Claude (Phase 2+)
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    model: str = field(default_factory=lambda: os.getenv("SUFLER_MODEL", "claude-sonnet-4-6"))
    mode: str = field(default_factory=lambda: os.getenv("SUFLER_MODE", "coach"))
    answer_lang: str = field(default_factory=lambda: os.getenv("SUFLER_ANSWER_LANG", "ru"))
    # Auto-answer each finalized recognized utterance (the live-prompter behaviour).
    auto_answer: bool = field(
        default_factory=lambda: os.getenv("SUFLER_AUTO_ANSWER", "true").strip().lower() in ("1", "true", "yes", "on")
    )
    # Number of points/theses the answer should contain.
    answer_points: int = field(default_factory=lambda: int(os.getenv("SUFLER_ANSWER_POINTS", "7") or "7"))

    # Answer LLM provider: "claude" (Anthropic, paid) or "gemini" (Google, free tier).
    llm_provider: str = field(default_factory=lambda: os.getenv("SUFLER_LLM_PROVIDER", "claude"))
    gemini_api_key: str = field(default_factory=lambda: os.getenv("SUFLER_GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("SUFLER_GEMINI_MODEL", "gemini-2.0-flash"))
    groq_api_key: str = field(default_factory=lambda: os.getenv("SUFLER_GROQ_API_KEY", ""))
    groq_model: str = field(
        default_factory=lambda: os.getenv("SUFLER_GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    )

    # Speech-to-text (Phase 5+)
    stt_engine: str = field(default_factory=lambda: os.getenv("SUFLER_STT_ENGINE", "mlx"))
    stt_model: str = field(default_factory=lambda: os.getenv("SUFLER_STT_MODEL", ""))
    stt_language: str = field(default_factory=lambda: os.getenv("SUFLER_STT_LANGUAGE", ""))
    loopback_device: str = field(default_factory=lambda: os.getenv("SUFLER_LOOPBACK_DEVICE", ""))

    # UI
    stealth: bool = field(
        default_factory=lambda: os.getenv("SUFLER_STEALTH", "").strip().lower() in ("1", "true", "yes", "on")
    )

    # Global hotkeys (Phase 3+, pynput syntax)
    hotkey_capture: str = field(default_factory=lambda: os.getenv("SUFLER_HOTKEY_CAPTURE", "<cmd>+<shift>+s"))
    hotkey_panic: str = field(default_factory=lambda: os.getenv("SUFLER_HOTKEY_PANIC", "<cmd>+<shift>+h"))
    hotkey_last: str = field(default_factory=lambda: os.getenv("SUFLER_HOTKEY_LAST", "<cmd>+<shift>+a"))


@dataclass
class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG: bool = True


@dataclass
class ProductionConfig(Config):
    """Production configuration."""

    DEBUG: bool = False  # pylint: disable=invalid-name
