"""
main.py (files/) - Orchestration entry point for the Freigabe maintenance window.

Called by the root main.py — you do not run this file directly.
"""

import sys
from pathlib import Path
from typing import Optional

from config import load_config
from utils.logger import log_run_footer, setup_logger
from utils.process_report import ProcessReport


def run(
    command: str,
    env_file: str = "deployment.env",
    only_steps: Optional[set[int]] = None,
    skip_steps: Optional[set[int]] = None,
) -> None:
    """
    Load configuration, set up logging, and dispatch the requested command.

    Args:
        command:  One of: preflight | list-security | start-01 | start-02 | ende
        env_file: Path to the deployment.env file (default: deployment.env)
        only_steps: Optional set of step IDs to run
        skip_steps: Optional set of step IDs to skip
    """
    cfg = load_config(env_file)
    setup_logger(cfg.log.log_dir, cfg.log.log_file_name, command=command)
    report = ProcessReport(
        command=command,
        log_dir=cfg.log.log_dir,
        only_steps=sorted(list(only_steps or set())),
        skip_steps=sorted(list(skip_steps or set())),
    )

    # Late imports so logger is configured before any module-level logging
    from workflows import ende, list_security, preflight, start_01, start_02

    dispatch = {
        "preflight":     preflight.run,
        "list-security": list_security.run,
        "start-01":      start_01.run,
        "start-02":      start_02.run,
        "ende":          ende.run,
    }

    if command not in dispatch:
        print(
            f"[ERROR] Unknown command '{command}'. "
            f"Valid commands: {', '.join(dispatch)}"
        )
        sys.exit(1)

    success = dispatch[command](
        cfg,
        only_steps=only_steps,
        skip_steps=skip_steps,
        report=report,
    )
    report.finalize(success)
    log_run_footer(success)
    sys.exit(0 if success else 1)
