from __future__ import annotations

import threading
from contextlib import contextmanager

# OpenCode stores session state in a shared SQLite DB (~/.local/share/opencode/).
# Concurrent `opencode run` processes cause "database is locked".
_OPENCODE_SEMAPHORE = threading.Semaphore(1)


@contextmanager
def opencode_session_lock():
    """Serialize OpenCode subprocess invocations across hub and sub-tasks."""
    _OPENCODE_SEMAPHORE.acquire()
    try:
        yield
    finally:
        _OPENCODE_SEMAPHORE.release()
