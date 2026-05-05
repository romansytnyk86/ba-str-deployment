"""
mstr/project.py - Project-level operations: disconnect users, load, unload.

Replaces these Command Manager commands:
    DISCONNECT USER CONNECTIONS FROM PROJECT "..."
    UNLOAD PROJECT "..."
    LOAD PROJECT "..."
"""

import logging
import traceback

from mstrio.connection import Connection
from mstrio.server.project import Project
from mstrio.users_and_groups.user_connections import UserConnections

logger = logging.getLogger("sgb2_freigabe")


def disconnect_users(conn: Connection, project_name: str) -> bool:
    """
    Disconnect all active user sessions from a project.
    CM equivalent: DISCONNECT USER CONNECTIONS FROM PROJECT "..."

    Admin/service sessions that cannot be disconnected are expected and
    reported as warnings — they do not cause a failure.
    Returns True if the step should be considered successful.
    """
    logger.info(f"  Disconnecting users from '{project_name}'...")
    try:
        uc = UserConnections(conn)
        uc.disconnect_users(force=True, project_name=project_name)
        remaining = uc.list_connections(project_name=project_name)
        if remaining:
            logger.warning(
                f"  {len(remaining)} session(s) could not be disconnected "
                "(likely admin/service sessions — safe to proceed):"
            )
            for s in remaining:
                logger.warning(
                    f"    User: {s.get('user_full_name', '?')} "
                    f"| App: {s.get('application_type', '?')} "
                    f"| Admin: {'Yes' if s.get('config_level') else 'No'}"
                )
        else:
            logger.info(f"  [OK] All users disconnected from '{project_name}'")
        return True
    except Exception as exc:
        msg = str(exc).lower()
        if "no session" in msg or "no active" in msg:
            logger.info(f"  [OK] No active users on '{project_name}'")
            return True
        logger.error(
            f"  [ERROR] Failed to disconnect users from '{project_name}': {exc}"
        )
        logger.debug(traceback.format_exc())
        return False


def unload_project(conn: Connection, project_name: str) -> bool:
    """
    Unload a project from the Intelligence Server (all cluster nodes).
    CM equivalent: UNLOAD PROJECT "..."
    Project.unload() natively handles single-server and multi-node clusters.
    Returns True on success.
    """
    logger.info(f"  Unloading '{project_name}'...")
    try:
        project = Project(connection=conn, name=project_name)
        if project.is_loaded():
            project.unload()
        else:
            logger.info(f"  Project '{project_name}' is already unloaded")
        logger.info(f"  [OK] Project '{project_name}' unloaded")
        return True
    except Exception as exc:
        logger.error(f"  [ERROR] Failed to unload '{project_name}': {exc}")
        logger.debug(traceback.format_exc())
        return False


def load_project(conn: Connection, project_name: str) -> bool:
    """
    Load a project on the Intelligence Server (all cluster nodes).
    CM equivalent: LOAD PROJECT "..."
    Project.load() natively handles single-server and multi-node clusters.
    Returns True on success.
    """
    logger.info(f"  Loading '{project_name}'...")
    try:
        project = Project(connection=conn, name=project_name)
        project.load()
        logger.info(f"  [OK] Project '{project_name}' loaded")
        return True
    except Exception as exc:
        logger.error(f"  [ERROR] Failed to load '{project_name}': {exc}")
        logger.debug(traceback.format_exc())
        return False
