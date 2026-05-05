"""
mstr/security.py - Security role operations: grant and revoke.

Replaces these Command Manager commands:
    REVOKE SECURITY ROLE "..." FROM GROUP "..." FROM PROJECT "..."
    GRANT SECURITY ROLE "..." TO GROUP "..." FOR PROJECT "..."
"""

import logging
import time
import traceback

from mstrio.connection import Connection
from mstrio.access_and_security.security_role import SecurityRole
from mstrio.server.project import Project
from mstrio.users_and_groups.user_group import UserGroup

logger = logging.getLogger("sgb2_freigabe")

# Grant retries: the project may still be initializing right after load_project()
MAX_RETRIES = 5
RETRY_DELAY_S = 15


def revoke_security_role(
    conn: Connection,
    role_name: str,
    group_name: str,
    project_name: str,
) -> bool:
    """
    Revoke a security role from a user group in a project.
    CM equivalent: REVOKE SECURITY ROLE "..." FROM GROUP "..." FROM PROJECT "..."
    Returns True on success.
    """
    logger.info(f"  Revoking '{role_name}' from '{group_name}' in '{project_name}'...")
    try:
        security_role = SecurityRole(conn, name=role_name)
        user_group = UserGroup(conn, name=group_name)
        project = Project(conn, name=project_name)

        security_role.revoke_from(members=[user_group], project=project)

        logger.info(f"  [OK] Revoked '{role_name}' from '{group_name}'")
        return True

    except Exception as exc:
        if "nothing to revoke" in str(exc).lower():
            logger.info(
                f"  [OK] '{role_name}' was not granted to '{group_name}' "
                f"in '{project_name}' — no action needed"
            )
            return True
        logger.error(
            f"  [ERROR] Failed to revoke '{role_name}' from '{group_name}' "
            f"in '{project_name}': {exc}"
        )
        logger.debug(traceback.format_exc())
        return False


def grant_security_role(
    conn: Connection,
    role_name: str,
    group_name: str,
    project_name: str,
) -> bool:
    """
    Grant a security role to a user group in a project.
    Retries on ERR001 (project still initializing after load).
    CM equivalent: GRANT SECURITY ROLE "..." TO GROUP "..." FOR PROJECT "..."
    Returns True on success.
    """
    logger.info(f"  Granting '{role_name}' to '{group_name}' in '{project_name}'...")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            security_role = SecurityRole(conn, name=role_name)
            user_group = UserGroup(conn, name=group_name)
            project = Project(conn, name=project_name)

            security_role.grant_to(members=[user_group], project=project)

            logger.info(f"  [OK] Granted '{role_name}' to '{group_name}'")
            return True

        except Exception as exc:
            err = str(exc).lower()
            if "err001" in err or "not ready" in err or "loading" in err:
                if attempt < MAX_RETRIES:
                    logger.warning(
                        f"  Project '{project_name}' not ready yet "
                        f"(attempt {attempt}/{MAX_RETRIES}). "
                        f"Retrying in {RETRY_DELAY_S}s..."
                    )
                    time.sleep(RETRY_DELAY_S)
                    continue
            logger.error(
                f"  [ERROR] Failed to grant '{role_name}' to '{group_name}' "
                f"in '{project_name}': {exc}"
            )
            logger.debug(traceback.format_exc())
            return False

    logger.error(
        f"  [ERROR] Gave up granting '{role_name}' to '{group_name}' "
        f"in '{project_name}' after {MAX_RETRIES} attempts"
    )
    return False
