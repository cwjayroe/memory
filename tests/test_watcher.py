from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

import watcher as watcher_module


# ---------------------------------------------------------------------------
# _DebounceHandler._should_process
# ---------------------------------------------------------------------------


def test_should_process_include_filter():
    handler = watcher_module._DebounceHandler(
        callback=lambda p: None,
        include=["*.py"],
        exclude=[],
        root=Path("/repo"),
    )
    assert handler._should_process(Path("/repo/src/main.py")) is True
    assert handler._should_process(Path("/repo/data/file.txt")) is False


def test_should_process_exclude_filter():
    handler = watcher_module._DebounceHandler(
        callback=lambda p: None,
        include=[],
        exclude=["*.pyc"],
        root=Path("/repo"),
    )
    assert handler._should_process(Path("/repo/src/main.py")) is True
    assert handler._should_process(Path("/repo/src/__pycache__/main.pyc")) is False


def test_should_process_path_outside_root():
    handler = watcher_module._DebounceHandler(
        callback=lambda p: None,
        include=[],
        exclude=[],
        root=Path("/repo"),
    )
    assert handler._should_process(Path("/other/file.py")) is False


def test_should_process_no_filters():
    handler = watcher_module._DebounceHandler(
        callback=lambda p: None,
        include=[],
        exclude=[],
        root=Path("/repo"),
    )
    assert handler._should_process(Path("/repo/anything.txt")) is True


# ---------------------------------------------------------------------------
# _DebounceHandler.on_modified / on_created
# ---------------------------------------------------------------------------


class _FakeEvent:
    def __init__(self, src_path: str, is_directory: bool = False):
        self.src_path = src_path
        self.is_directory = is_directory


def test_on_modified_adds_to_pending():
    handler = watcher_module._DebounceHandler(
        callback=lambda p: None,
        include=[],
        exclude=[],
        root=Path("/repo"),
        debounce_seconds=999,
    )
    event = _FakeEvent("/repo/test.py")
    handler.on_modified(event)
    assert Path("/repo/test.py") in handler._pending
    if handler._timer:
        handler._timer.cancel()


def test_on_modified_skips_directories():
    handler = watcher_module._DebounceHandler(
        callback=lambda p: None,
        include=[],
        exclude=[],
        root=Path("/repo"),
    )
    event = _FakeEvent("/repo/subdir", is_directory=True)
    handler.on_modified(event)
    assert len(handler._pending) == 0


def test_on_created_delegates_to_on_modified():
    handler = watcher_module._DebounceHandler(
        callback=lambda p: None,
        include=[],
        exclude=[],
        root=Path("/repo"),
        debounce_seconds=999,
    )
    event = _FakeEvent("/repo/new.py")
    handler.on_created(event)
    assert Path("/repo/new.py") in handler._pending
    if handler._timer:
        handler._timer.cancel()


# ---------------------------------------------------------------------------
# _DebounceHandler._flush
# ---------------------------------------------------------------------------


def test_flush_invokes_callback():
    results = []
    handler = watcher_module._DebounceHandler(
        callback=lambda p: results.append(p),
        include=[],
        exclude=[],
        root=Path("/repo"),
    )
    handler._pending[Path("/repo/file.py")] = time.time()
    handler._flush()
    assert Path("/repo/file.py") in results
    assert len(handler._pending) == 0


def test_flush_handles_callback_error(caplog):
    def bad_callback(p):
        raise ValueError("callback error")

    handler = watcher_module._DebounceHandler(
        callback=bad_callback,
        include=[],
        exclude=[],
        root=Path("/repo"),
    )
    handler._pending[Path("/repo/file.py")] = time.time()
    handler._flush()
    assert len(handler._pending) == 0

