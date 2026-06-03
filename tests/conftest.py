# tests/conftest.py

"""Shared pytest configuration and test-environment setup."""

import os


def pytest_configure() -> None:
    """Ensure runtime directories the logger expects exist before tests import it."""
    os.makedirs("tmp/logs", exist_ok=True)
