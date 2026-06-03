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

    # Speech-to-text (Phase 5+)
    stt_engine: str = field(default_factory=lambda: os.getenv("SUFLER_STT_ENGINE", "mlx"))
    stt_model: str = field(default_factory=lambda: os.getenv("SUFLER_STT_MODEL", ""))

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
