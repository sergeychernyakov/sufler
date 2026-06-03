# tests/ui/conftest.py

"""Pytest fixtures and headless Qt setup for the overlay tests.

The ``QT_QPA_PLATFORM`` environment variable is forced to ``offscreen`` *before*
any PyQt6 import so the suite runs without a display (CI / headless macOS).
"""

import os

# IMPORTANT: must run before PyQt6 is imported anywhere in the test session.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The shared logger writes rotating files under tmp/logs; make sure it exists.
os.makedirs("tmp/logs", exist_ok=True)

import pytest  # noqa: E402  (intentional: env must be set before imports below)

from src.ui.overlay import Overlay  # noqa: E402


@pytest.fixture()
def overlay(qtbot):
    """Provides a fresh :class:`~src.ui.overlay.Overlay` registered with qtbot.

    Args:
        qtbot: The pytest-qt bot fixture managing the Qt event loop.

    Returns:
        Overlay: A new overlay instance added to ``qtbot`` for lifecycle mgmt.
    """
    widget = Overlay()
    qtbot.addWidget(widget)
    return widget
