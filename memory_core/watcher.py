"""File watcher for auto-ingest on file changes (watch mode)."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class _DebounceHandler(FileSystemEventHandler):
    """Debounced file-change handler that calls a callback after a quiet period."""

    def __init__(
        self,
        callback: Callable[[Path], None],
        include: list[str],
        exclude: list[str],
        root: Path,
        debounce_seconds: float = 3.0,
    ): 
        super().__init__()
        self._callback = callback
        self._include = include
        self._exclude = exclude
        self._root = root
        self._debounce_seconds = debounce_seconds
        self._pending: dict[Path, float] = {}
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def _should_process(self, path: Path) -> bool:
        import fnmatch
        try:
            rel = path.relative_to(self._root).as_posix()
        except ValueError:
            return False
        if self._include and not any(fnmatch.fnmatch(rel, pat) for pat in self._include):
            return False
        if self._exclude and any(fnmatch.fnmatch(rel, pat) for pat in self._exclude):
            return False
        return True

    def _schedule_flush(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self._debounce_seconds, self._flush)
        self._timer.daemon = True
        self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            paths = list(self._pending.keys())
            self._pending.clear()
        for path in paths:
            try:
                self._callback(path)
            except Exception:
                LOGGER.exception("Error ingesting %s", path)

    def on_modified(self, event: Any) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._should_process(path):
            with self._lock:
                self._pending[path] = time.time()
            self._schedule_flush()

    def on_created(self, event: Any) -> None:  # type: ignore[override]
        self.on_modified(event)


def watch_repo(
    *,
    root: Path,
    project_id: str,
    repo: str,
    include: list[str],
    exclude: list[str],
    debounce_seconds: float = 3.0,
    mem_manager: Any = None,
) -> None:
    """Watch a repo directory and auto-ingest changed files. Blocks until interrupted."""
    from ingest import ingest_file

    mm = mem_manager
    if mm is None:
        from memory_manager import MemoryManager  # type: ignore
        mm = MemoryManager(logger=LOGGER)

    def on_change(path: Path) -> None:
        LOGGER.info("File changed: %s — re-ingesting...", path)
        items = mm.get_all_items(project_id)
        deleted, stored = ingest_file(
            items=[item.as_dict() for item in items],
            project_id=project_id,
            repo=repo,
            path=path,
            mode="mixed",
            tags=[],
            mem_manager=mm,
        )
        LOGGER.info("Re-ingested %s: deleted=%d stored=%d", path.name, deleted, stored)
        print(f"[watch] {path.name}: deleted={deleted} stored={stored}")

    handler = _DebounceHandler(
        callback=on_change,
        include=include,
        exclude=exclude,
        root=root,
        debounce_seconds=debounce_seconds,
    )

    observer = Observer()
    observer.schedule(handler, str(root), recursive=True)
    observer.start()
    print(f"[watch] Watching {root} for project={project_id} repo={repo}. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

