"""
utils/logger.py - Logging setup for the Freigabe deployment tool.

Two output channels run simultaneously:

  CONSOLE (stdout):
    - Shows INFO and above
    - Clean format: just the message, no timestamp clutter

  LOG FILE (LOG_DIR/LOG_FILE_NAME from deployment.env):
    - Shows DEBUG and above
    - Every line is timestamped and level-tagged
    - Appends to existing file; each run is bracketed with a header/footer
    - Rotates automatically: max 5 MB × 5 files
"""

import logging
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


_run_start: Optional[datetime] = None
_run_command: str = ""


class _DetailFormatter(logging.Formatter):
    """File formatter that appends full tracebacks on ERROR/CRITICAL records."""
    def formatException(self, exc_info) -> str:
        return "".join(traceback.format_exception(*exc_info)).rstrip()


def setup_logger(log_dir: Path, log_file_name: str, command: str = "") -> logging.Logger:
    """
    Configure the application logger and write a run-start header to the log file.
    Call once at startup before running any workflow.
    """
    global _run_start, _run_command
    _run_start = datetime.now()
    _run_command = command or "unknown"

    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / log_file_name

    logger = logging.getLogger("sgb2_freigabe")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    file_handler = RotatingFileHandler(
        log_path,
        mode="a",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_DetailFormatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console_handler)

    _write_separator(
        file_handler,
        f"RUN STARTED: {_run_start.strftime('%Y-%m-%d %H:%M:%S')}  "
        f"|  command: {_run_command}",
    )

    logger.info(f"Log file: {log_path.absolute()}")
    return logger


def log_run_footer(success: bool) -> None:
    """
    Write a run-end footer to the log file with duration and result.
    Call at the very end of main.py, after the workflow returns.
    """
    logger = logging.getLogger("sgb2_freigabe")

    duration = ""
    if _run_start:
        elapsed = datetime.now() - _run_start
        duration = f"  |  Duration: {str(elapsed).split('.')[0]}"

    result = "SUCCESS" if success else "FAILED"

    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            _write_separator(
                handler,
                f"RUN FINISHED: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                f"  |  {result}{duration}",
            )


def get_logger() -> logging.Logger:
    """Return the already-configured application logger."""
    return logging.getLogger("sgb2_freigabe")


def _write_separator(handler: logging.Handler, label: str) -> None:
    line = "=" * 60
    for text in [line, label, line]:
        record = logging.LogRecord(
            name="sgb2_freigabe",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=text,
            args=(),
            exc_info=None,
        )
        handler.emit(record)
