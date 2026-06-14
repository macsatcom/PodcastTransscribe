import logging
import os

_DEFAULT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """Configure root logging once, with a consistent format.

    Level is taken from the LOG_LEVEL env var (default INFO). This is a plain
    text formatter — no JSON, no log shipping (intentionally minimal).
    """
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format=_DEFAULT_FORMAT,
        datefmt=_DEFAULT_DATEFMT,
    )
