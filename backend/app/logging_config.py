"""Application logging setup.

Supports the standard levels DEBUG, INFO, WARNING, ERROR and CRITICAL.
The level is taken from the LOG_LEVEL environment variable (default: INFO).
Logs go to the console and to a rotating file in backend/logs/app.log.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "app.log"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def setup_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    if level_name not in VALID_LEVELS:
        level_name = "INFO"

    LOG_DIR.mkdir(exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level_name)
    # Replace existing handlers so auto-reload doesn't duplicate output.
    root.handlers = [console_handler, file_handler]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
