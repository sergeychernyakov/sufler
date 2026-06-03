# src/config/settings.py

"""
Settings Module

This module defines configuration classes for different environments
(Development and Production) using dataclasses. It loads environment
variables from a `.env` file and sets various application settings.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Base configuration class."""

    DEBUG: bool = False  # pylint: disable=invalid-name
    APP_ENV = os.getenv("APP_ENV")


@dataclass
class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG: bool = True


@dataclass
class ProductionConfig(Config):
    """Production configuration."""

    DEBUG: bool = False  # pylint: disable=invalid-name
