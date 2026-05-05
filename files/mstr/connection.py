"""
mstr/connection.py - Strategy connection factory.

Provides a reusable context manager that opens and cleanly closes
a Strategy connection. Used by all workflow steps.
"""

import logging
import traceback
from contextlib import contextmanager
from typing import Optional

from mstrio.connection import Connection
from config import MstrConfig

logger = logging.getLogger("sgb2_freigabe")


@contextmanager
def mstr_connection(cfg: MstrConfig, project_name: Optional[str] = None):
    """
    Context manager that opens a Strategy connection and closes it on exit.

    Logs connection open/close at DEBUG level (visible in log file, not console).
    Any error during close is logged as a warning rather than raised, so it
    does not mask the original workflow error.

    Args:
        cfg:          MstrConfig (from deployment.env)
        project_name: Optional project context. Leave None for server-level
                      operations (load/unload, security roles, DB connections).
    """
    conn = None
    try:
        logger.debug(
            f"Opening connection -> {cfg.base_url} "
            f"(user: {cfg.username}, "
            f"project: {project_name or 'server-level'})"
        )
        conn = Connection(
            base_url=cfg.base_url,
            username=cfg.username,
            password=cfg.password,
            login_mode=cfg.login_mode,
            **({"project_name": project_name} if project_name else {}),
        )
        logger.debug("Connection established")
        yield conn

    except Exception as exc:
        logger.error(f"Failed to connect to {cfg.base_url}: {exc}")
        logger.debug(traceback.format_exc())
        raise

    finally:
        if conn:
            try:
                conn.close()
                logger.debug("Connection closed")
            except Exception as exc:
                logger.warning(f"Error closing connection: {exc}")
