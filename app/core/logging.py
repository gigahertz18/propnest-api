"""
app/core/logging.py

Centralised logging setup for PropNest.

Call `setup_logging()` once at startup (in main.py's lifespan).
After that, every module just does:

    import logging
    logger = logging.getLogger(__name__)

Behaviour by environment
────────────────────────
  dev / test / unittest  → console DEBUG + file DEBUG
  staging                → console INFO  + file INFO
  prod                   → console WARNING + file INFO (file keeps more)

Log files
─────────
  logs/propnest.log          — current log (rotated at 10 MB, 5 backups kept)

The logs/ directory is created automatically if it doesn't exist.
Add  logs/  to .gitignore so log files are never committed.
"""

import logging
import logging.handlers
import sys
from pathlib import Path

# ─── Formatters ───────────────────────────────────────────────────────────────

_CONSOLE_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_FILE_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


class _ColourFormatter(logging.Formatter):
    """
    Adds ANSI colour codes to the levelname in console output.
    Falls back gracefully when stdout is not a TTY (e.g. Docker log collectors).
    """

    _COLOURS = {
        logging.DEBUG: "\033[36m",  # cyan
        logging.INFO: "\033[32m",  # green
        logging.WARNING: "\033[33m",  # yellow
        logging.ERROR: "\033[31m",  # red
        logging.CRITICAL: "\033[35m",  # magenta
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        if sys.stdout.isatty():
            colour = self._COLOURS.get(record.levelno, "")
            # Colour only the levelname portion so the rest stays readable
            formatted = formatted.replace(
                record.levelname,
                f"{colour}{record.levelname}{self._RESET}",
                1,
            )
        return formatted


# ─── Public API ───────────────────────────────────────────────────────────────


def setup_logging(env: str = "dev", log_dir: str = "logs") -> None:
    """
    Configure the root logger with a console handler and a rotating file handler.

    Args:
        env:     The current environment string (dev / test / unittest / staging / prod).
        log_dir: Directory where log files are written. Created automatically if absent.
    """

    # Resolve log levels per environment
    _LEVEL_MAP: dict[str, tuple[int, int]] = {
        # env          console level   file level
        "dev": (logging.DEBUG, logging.DEBUG),
        "test": (logging.DEBUG, logging.DEBUG),
        "unittest": (logging.DEBUG, logging.DEBUG),
        "staging": (logging.INFO, logging.INFO),
        "prod": (logging.WARNING, logging.INFO),
    }
    console_level, file_level = _LEVEL_MAP.get(env, (logging.INFO, logging.INFO))

    # Root logger — set to the lowest of the two levels so neither handler is
    # blocked before it even gets a chance to filter.
    root = logging.getLogger()
    root.setLevel(min(console_level, file_level))

    # Avoid adding duplicate handlers on repeated calls (e.g. test reloads)
    if root.handlers:
        root.handlers.clear()

    # ── Console handler ───────────────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(_ColourFormatter(fmt=_CONSOLE_FMT, datefmt=_DATE_FMT))
    root.addHandler(console_handler)

    # ── File handler (rotating) ───────────────────────────────────────────────
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_path / "propnest.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB per file
        backupCount=5,  # keep propnest.log.1 … propnest.log.5
        encoding="utf-8",
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(logging.Formatter(fmt=_FILE_FMT, datefmt=_DATE_FMT))
    root.addHandler(file_handler)

    # ── Silence noisy third-party loggers ────────────────────────────────────
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO if env in ("dev", "unittest") else logging.WARNING)
    logging.getLogger("passlib").setLevel(logging.WARNING)

    # Confirm logging is live
    log = logging.getLogger(__name__)
    log.debug(
        "Logging initialised [env=%s | console=%s | file=%s]",
        env,
        logging.getLevelName(console_level),
        logging.getLevelName(file_level),
    )
