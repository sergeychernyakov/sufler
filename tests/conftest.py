# tests/conftest.py

"""Shared pytest configuration and test-environment setup."""

import os

# Run Qt headless for the whole suite (must be set before PyQt6 is imported).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_configure() -> None:
    """Ensure runtime directories the logger expects exist before tests import it."""
    os.makedirs("tmp/logs", exist_ok=True)
