"""
utils/logger.py - Logging setup for the deployment tool.

Provides two output channels that run simultaneously:

  CONSOLE (stdout):
    - Shows INFO and above
    - Clean format: just the message, no timestamp clutter
    - Suitable for watching a run interactively

  LOG FILE (LOG_DIR/LOG_FILE_NAME from deployment.env):
    - Shows DEBUG and above (more detail than console)
    - Every line is timestamped and level-tagged
    - Appends to existing file so all runs are preserved in history
    - Each run is clearly separated with a header/footer so multiple
      runs in the same file are easy to tell apart
    - Full exception tracebacks are written here (not shown on console)
    - Rotates automatically: keeps the 5 most recent log files,
      max 5 MB each, so the folder never fills up

Typical log file output:
    ============================================================
    RUN STARTED: 2025-12-01 09:14:32  |  ohne-backup
    ============================================================
    2025-12-01 09:14:32 | INFO     | Connecting to Strategy...
    2025-12-01 09:14:33 | INFO     | [Step 1/4] Disconnect user connections
    2025-12-01 09:14:33 | DEBUG    | Opening connection to http://localhost:8080/...
    2025-12-01 09:14:35 | INFO     |   [OK] All users disconnected from 'SGB II MaEnde'
    ...
    2025-12-01 09:14:58 | INFO     | [SUCCESS] Workflow completed successfully
    ============================================================
    RUN FINISHED: 2025-12-01 09:14:58  |  Duration: 0:00:26
    ============================================================
"""

import logging
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


# ── Internal state ────────────────────────────────────────────────────────────
# Stored so the run footer can report elapsed time
_run_start: Optional[datetime] = None
_run_command: str = ""


# ── Custom formatter: writes full tracebacks to file ─────────────────────────

class _DetailFormatter(logging.Formatter):
    """
    File formatter that appends the full traceback on ERROR/CRITICAL records.
    The console formatter intentionally omits tracebacks to keep output clean.
    """
    def formatException(self, exc_info) -> str:
        return "".join(traceback.format_exception(*exc_info)).rstrip()


# ── Public API ────────────────────────────────────────────────────────────────

def setup_logger(log_dir: Path, log_file_name: str, command: str = "") -> logging.Logger:
    """
    Configure the application logger and write a run-start header to the log file.

    Call this once at the start of main.py before running any workflow.

    Args:
        log_dir:       Directory for the log file (from LOG_DIR in deployment.env)
        log_file_name: Log file name (from LOG_FILE_NAME in deployment.env)
        command:       The CLI command being run (e.g. "ohne-backup"), used in
                       the run header/footer for easy scanning of the log history

    Returns:
        The configured logger (also accessible via get_logger() anywhere in the app)
    """
    global _run_start, _run_command
    _run_start = datetime.now()
    _run_command = command or "unknown"

    # Fix Windows CP1252 console encoding so Unicode symbols don't crash
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass  # Python < 3.7 — symbols replaced with ASCII equivalents anyway

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / log_file_name

    logger = logging.getLogger("sgb2_maende")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # ── File handler ──────────────────────────────────────────────────
    # Rotating: max 5 MB per file, keep 5 backups
    # -> LOG_SGB II MaEnde.txt, LOG_SGB II MaEnde.txt.1, ..., .5
    file_handler = RotatingFileHandler(
        log_path,
        mode="a",
        maxBytes=5 * 1024 * 1024,   # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_DetailFormatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)

    # ── Console handler ───────────────────────────────────────────────
    # Clean output: just the message, no timestamps
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console_handler)

    # ── Run-start header (file only) ──────────────────────────────────
    # Written directly to the file handler so the console stays clean
    _write_separator(file_handler,
                     f"RUN STARTED: {_run_start.strftime('%Y-%m-%d %H:%M:%S')}  "
                     f"|  command: {_run_command}")

    logger.info(f"Log file: {log_path.absolute()}")
    return logger


def log_run_footer(success: bool) -> None:
    """
    Write a run-end footer to the log file with duration and result.

    Call this at the very end of main.py, after the workflow returns.
    Not written to console — only to the file.

    Args:
        success: Whether the workflow completed without errors.
    """
    logger = logging.getLogger("sgb2_maende")

    duration = ""
    if _run_start:
        elapsed = datetime.now() - _run_start
        # Format as H:MM:SS, stripping microseconds
        duration = f"  |  Duration: {str(elapsed).split('.')[0]}"

    result = "SUCCESS" if success else "FAILED"

    # Write directly to file handlers only (skip console)
    for handler in logger.handlers:
        if isinstance(handler, (RotatingFileHandler,)):
            _write_separator(
                handler,
                f"RUN FINISHED: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                f"  |  {result}{duration}"
            )


def get_logger() -> logging.Logger:
    """
    Return the already-configured application logger.

    Use this in any module that needs to log:
        from utils.logger import get_logger
        logger = get_logger()
    """
    return logging.getLogger("sgb2_maende")


# ── Internal helper ───────────────────────────────────────────────────────────

def _write_separator(handler: logging.Handler, label: str) -> None:
    """Write a visual separator line directly through a handler (no level filtering)."""
    line = "=" * 60
    for text in [line, label, line]:
        record = logging.LogRecord(
            name="sgb2_maende",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=text,
            args=(),
            exc_info=None,
        )
        handler.emit(record)
