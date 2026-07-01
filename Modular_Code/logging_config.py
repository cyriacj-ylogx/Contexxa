"""Structured logging for the airline support bot.

Two log streams under <project>/logs/:
  - app.log       human-readable application log (rotating, 5 MB x 3)
  - queries.jsonl one JSON object per line for analysis (rotating, 10 MB x 5)

All write paths swallow exceptions: a full disk or locked file must never
break a chat request.
"""

import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

_configured = False

app_log = logging.getLogger("airline.app")
_query_log = logging.getLogger("airline.queries")


def setup_logging(log_dir: str = _LOG_DIR) -> None:
    """Idempotent logger setup — safe under uvicorn reload."""
    global _configured
    if _configured:
        return
    try:
        os.makedirs(log_dir, exist_ok=True)

        app_handler = RotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        app_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        app_log.addHandler(app_handler)
        app_log.setLevel(logging.INFO)
        app_log.propagate = False

        query_handler = RotatingFileHandler(
            os.path.join(log_dir, "queries.jsonl"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        query_handler.setFormatter(logging.Formatter("%(message)s"))
        _query_log.addHandler(query_handler)
        _query_log.setLevel(logging.INFO)
        _query_log.propagate = False

        _configured = True
    except Exception:
        # Logging must never prevent the app from starting.
        _configured = True


def log_event(event_type: str, **fields) -> None:
    """Write one structured JSON line to queries.jsonl. Never raises."""
    try:
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event_type}
        record.update(fields)
        _query_log.info(json.dumps(record, ensure_ascii=False, default=str))
    except Exception:
        pass


def log_app(message: str, level: int = logging.INFO) -> None:
    """Write to app.log. Never raises."""
    try:
        app_log.log(level, message)
    except Exception:
        pass
