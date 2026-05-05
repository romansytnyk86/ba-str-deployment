"""
mstr/dbconnection.py - Alter a datasource connection's catalog string.

Replaces this Command Manager command:
    ALTER DBCONNECTION "..." CATALOG "..."
"""

import logging
import re
import traceback

from mstrio.connection import Connection
from mstrio.datasources import DatasourceConnection

logger = logging.getLogger("sgb2_freigabe")


def alter_db_connection_catalog(
    conn: Connection,
    connection_name: str,
    new_catalog: str,
) -> bool:
    """
    Update the CATALOG={...} part of a datasource connection string.
    CM equivalent: ALTER DBCONNECTION "<connection_name>" CATALOG "<new_catalog>"

    Logs the old and new connection strings at DEBUG level for audit purposes.
    Returns True on success.
    """
    logger.info(f"  Altering DB connection '{connection_name}'...")
    try:
        ds_conn = DatasourceConnection(conn, name=connection_name)

        old_string = ds_conn.connection_string
        logger.debug(f"  Current connection string: {old_string}")

        updated_string = re.sub(
            r"CATALOG=\{.*?\}",
            f"CATALOG={{{new_catalog}}}",
            old_string,
            flags=re.IGNORECASE,
        )

        ds_conn.alter(connection_string=updated_string)
        ds_conn.fetch()

        logger.info(f"  [OK] Catalog updated to '{new_catalog}'")
        logger.debug(f"  Updated connection string: {ds_conn.connection_string}")
        return True

    except Exception as exc:
        logger.error(
            f"  [ERROR] Failed to alter DB connection '{connection_name}': {exc}"
        )
        logger.debug(traceback.format_exc())
        return False


def list_db_connection_properties(
    conn: Connection,
    connection_name: str,
) -> None:
    """
    Log the current properties of a datasource connection (informational).
    CM equivalent: LIST PROPERTIES FOR DBCONNECTION "..."
    This step is read-only and never raises.
    """
    try:
        ds_conn = DatasourceConnection(conn, name=connection_name)
        ds_conn.fetch()
        logger.info(
            f"  [INFO] DB connection '{connection_name}': "
            f"connection_string='{ds_conn.connection_string}'"
        )
    except Exception as exc:
        logger.warning(
            f"  [WARN] Could not list properties for '{connection_name}': {exc}"
        )
