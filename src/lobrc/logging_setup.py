"""Logging setup shared by every CLI command.

Finance concept: an audit trail. When a trading result looks surprising, timestamped logs are
how you find out what the system actually did.
"""
from __future__ import annotations

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging once with the project format."""
    logging.basicConfig(level=level, format=LOG_FORMAT)
