import sys
from datetime import datetime
from pathlib import Path

_listeners = []


class _Tee:
    def __init__(self, stream, file):
        self.stream, self.file = stream, file

    def write(self, text: str) -> int:
        self.file.write(text)
        self.file.flush()
        for listener in _listeners:
            listener(text)
        return self.stream.write(text)

    def flush(self) -> None:
        self.stream.flush()
        self.file.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def start(log_dir: Path = Path("logs")) -> Path:
    """Copy everything printed to the console (including errors) into logs/<time>.log."""
    log_dir.mkdir(exist_ok=True)
    path = log_dir / f"{datetime.now():%Y%m%d-%H%M%S}.log"
    file = open(path, "a", encoding="utf-8")
    sys.stdout = _Tee(sys.stdout, file)
    sys.stderr = _Tee(sys.stderr, file)
    return path


def subscribe(listener) -> None:
    """Call listener(text) for everything printed after start()."""
    _listeners.append(listener)
