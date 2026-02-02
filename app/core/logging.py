from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configure basic console logging.

    For a PoC we keep logging minimal. Uvicorn will also configure its own loggers,
    but having a consistent root logger helps when debugging ML/model loading.
    """

    root = logging.getLogger()
    root.setLevel(level.upper())

    # Avoid duplicate handlers if the module is imported multiple times.
    if any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        return

    handler = logging.StreamHandler(sys.stdout)
    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(handler)

    # Quiet noisy loggers if needed.
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
