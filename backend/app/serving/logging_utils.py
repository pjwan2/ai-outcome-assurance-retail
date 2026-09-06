"""Structured (JSON) logging for the model serving slice — one log line per
lifecycle event, machine-parseable rather than free-text, so a real log
pipeline (or a test's `caplog`) can filter/aggregate on fields instead of
regexing prose.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("app.serving")


def log_event(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str))
