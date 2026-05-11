"""structlog JSON logging setup."""
from __future__ import annotations

import logging
import sys
from typing import Any, TextIO

import structlog


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    logging.basicConfig(format="%(message)s", stream=stream, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(file=stream),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
