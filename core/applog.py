"""In-app log: the last lines of the YaSave log, so diagnostics do not need adb."""
import collections
import logging
import threading
import time

MAX_LINES = 200

_lines = collections.deque(maxlen=MAX_LINES)
_lock = threading.Lock()


class RingHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        with _lock:
            _lines.append(msg)


def install(level=logging.INFO):
    """Attach the ring buffer to the root logger (idempotent)."""
    root = logging.getLogger()
    if any(isinstance(h, RingHandler) for h in root.handlers):
        return
    h = RingHandler(level)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname).1s [%(name)s] %(message)s", "%H:%M:%S"))
    root.addHandler(h)
    if root.level > level or root.level == logging.NOTSET:
        root.setLevel(level)


def add(source: str, message: str):
    """Lines coming from the page (JS side of the chain)."""
    with _lock:
        _lines.append(f"{time.strftime('%H:%M:%S')} I [{source}] {message[:500]}")


def text() -> str:
    with _lock:
        return "\n".join(_lines)
