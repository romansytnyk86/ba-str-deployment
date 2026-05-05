"""
mstr/schema.py - Schema update operation.

Replaces this Command Manager command:
    UPDATE SCHEMA REFRESHSCHEMA RECALTABLEKEYS RECALTABLELOGICAL RECALOBJECTCACHE
    FOR PROJECT "..."
"""

import logging

from mstrio.connection import Connection
from mstrio.modeling.schema import SchemaManagement, SchemaUpdateType

logger = logging.getLogger("sgb2_freigabe")


def update_schema(conn: Connection, project_id: str) -> bool:
    """
    Run a full schema update for a project.

    CM equivalent:
        UPDATE SCHEMA REFRESHSCHEMA RECALTABLEKEYS RECALTABLELOGICAL
        RECALOBJECTCACHE FOR PROJECT "..."

    Args:
        conn:       Active Strategy connection scoped to the project
        project_id: MSTR project ID (required by SchemaManagement)

    Returns True on success.
    """
    logger.info(f"  Updating schema for project ID '{project_id}'...")
    try:
        schema_mgmt = SchemaManagement(conn, project_id=project_id)

        update_types = [
            SchemaUpdateType.TABLE_KEY,            # RECALTABLEKEYS
            SchemaUpdateType.LOGICAL_SIZE,         # RECALTABLELOGICAL
            SchemaUpdateType.CLEAR_ELEMENT_CACHE,  # RECALOBJECTCACHE
        ]

        schema_mgmt.reload(update_types=update_types, respond_async=False)

        logger.info("  [OK] Schema update completed")
        return True

    except Exception as exc:
        logger.error(f"  [ERROR] Schema update failed: {exc}")
        return False
