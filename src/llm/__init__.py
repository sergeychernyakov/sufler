# src/llm/__init__.py

"""LLM package — Anthropic Claude client with streaming and answer/coach modes (Phase 2)."""

from src.llm.claude import ClaudeClient

__all__ = ["ClaudeClient"]
