# src/vision/__init__.py

"""
Vision Package

This package groups screen-capture utilities used to feed visual context to the
multimodal Claude model (Phase 2). The public surface is intentionally small:
:func:`src.vision.screenshot.grab_screen` returns a base64-encoded PNG of the
screen (or a region of it).
"""

from src.vision.screenshot import grab_screen

__all__ = ["grab_screen"]
