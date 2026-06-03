# tests/test_main.py

"""Smoke tests for the application entry point."""

import pytest

import main as main_module


def _raise_on(trigger, exc):
    """Build a ``logger.info`` replacement that raises ``exc`` for a given message."""

    def _info(message, *args, **kwargs):
        if trigger in str(message):
            raise exc

    return _info


def test_main_happy_path_returns_none() -> None:
    assert main_module.main() is None


def test_main_exits_zero_on_keyboard_interrupt(monkeypatch) -> None:
    monkeypatch.setattr(main_module.logger, "info", _raise_on("initialized", KeyboardInterrupt()))
    with pytest.raises(SystemExit) as exc_info:
        main_module.main()
    assert exc_info.value.code == 0


def test_main_exits_one_on_runtime_error(monkeypatch) -> None:
    monkeypatch.setattr(main_module.logger, "info", _raise_on("initialized", RuntimeError("boom")))
    with pytest.raises(SystemExit) as exc_info:
        main_module.main()
    assert exc_info.value.code == 1
