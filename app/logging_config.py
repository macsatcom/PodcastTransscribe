import json
import logging
import os
from logging.handlers import RotatingFileHandler

_DEFAULT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Standard LogRecord attributes that should NOT be surfaced as extra fields in JSON output.
_LOG_RECORD_BUILTINS = frozenset(
    {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "thread",
        "threadName",
        "stack_info",
        "exc_info",
        "exc_text",
        "taskName",
        "asctime",
        "message",
    }
)


class _JSONLinesHandler(RotatingFileHandler):
    """Emit log records as newline-delimited JSON (JSON Lines format).

    Any ``extra={...}`` kwargs passed at call-site are merged into the
    top-level JSON object, making it easy to add structured context such as
    episode_id, stage, cost, etc.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry: dict = {
                "ts": self.formatTime(record, datefmt=_DEFAULT_DATEFMT),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            # Merge caller-supplied extra fields.
            for key, val in record.__dict__.items():
                if key not in _LOG_RECORD_BUILTINS:
                    entry[key] = val
            self.stream.write(json.dumps(entry, default=str) + "\n")
            self.flush()
        except Exception:
            self.handleError(record)


def setup_logging(log_dir: str | None = None) -> None:
    """Configure root logging once, with a consistent format.

    Level is taken from the LOG_LEVEL env var (default INFO). This is a plain
    text formatter — no JSON, no log shipping (intentionally minimal).

    When *log_dir* is provided, two additional file handlers are attached:
    - ``app.log``  — plain text, WARNING+, 10 MB × 5 rotations (50 MB max)
    - ``transcription_events.jsonl`` — structured JSON Lines on the
      ``app.events.transcription`` logger, 50 MB × 3 rotations (150 MB max)
    """
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format=_DEFAULT_FORMAT,
        datefmt=_DEFAULT_DATEFMT,
    )

    if not log_dir:
        return

    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as exc:
        logging.warning(
            "Could not create log directory %s: %s — file logging disabled",
            log_dir,
            exc,
        )
        return

    # Plain-text rotating log — WARNING+ from all loggers.
    plain_handler = RotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    plain_handler.setLevel(logging.WARNING)
    plain_handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT))
    logging.getLogger().addHandler(plain_handler)

    # JSONL structured event log — dedicated logger, all levels, no console propagation.
    jsonl_handler = _JSONLinesHandler(
        os.path.join(log_dir, "transcription_events.jsonl"),
        maxBytes=50 * 1024 * 1024,  # 50 MB
        backupCount=3,
        encoding="utf-8",
    )
    jsonl_handler.setLevel(logging.DEBUG)
    event_logger = logging.getLogger("app.events.transcription")
    event_logger.addHandler(jsonl_handler)
    event_logger.propagate = False  # do not bubble to console / plain-text handler
    event_logger.setLevel(logging.DEBUG)
