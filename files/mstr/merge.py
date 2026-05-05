"""
mstr/merge.py - Cross-environment project merge via the mstrio-py Migration API.

Replaces the ProjectMerge.exe CLI call in BAT_SGBII_Freigabe_Start_Wartungsfenster_02.bat:

    projectmerge -f "SGB II S2S/PM_SGB II S2S_-_Integration2Freigabe.xml"
                 -sn Administrator -sp <password>
                 -dn Administrator -dp <password>

The original XML specifies:
    Source:      BICO-Integration-IS.dst.baintern.de  →  Project: SGB II S2S
    Destination: BICO-Freigabe-IS.dst.baintern.de     →  Project: SGB II S2S
    Rules:
        Application  →  Replace
        Configuration → UseExisting
        Schema        → Replace
    Type-level overrides: see PM_SGB II S2S_-_Integration2Freigabe.xml

mstrio-py Migration API
───────────────────────
Migration.create_project_merge_migration() creates a PROJECT_MERGE migration
package on the source environment.  The package is then imported on the target
via migration.migrate().

ProjectMergePackageTocView maps the XML CategoryLevel rules:
  application=Action.REPLACE, configuration=Action.USE_EXISTING, schema=Action.REPLACE

NOTE: The mstrio-py ProjectMerge API (create_project_merge_migration +
migrate) is the closest available replacement for the projectmerge.exe CLI.
It migrates all project objects according to the toc_view rules.
If the API version on your environment does not support this feature, the
method will raise a VersionException and should be handled with a manual
projectmerge.exe run as a fallback.
"""

import logging
import traceback
from datetime import datetime

from mstrio.connection import Connection
from mstrio.object_management.migration import Migration
from mstrio.object_management.migration.package import (
    Action,
    ProjectMergePackageTocView,
)

logger = logging.getLogger("sgb2_freigabe")


def project_merge(
    source_conn: Connection,
    target_conn: Connection,
    project_name: str,
    migration_name_prefix: str = "SGB II Freigabe Integration2Freigabe",
) -> bool:
    """
    Merge all objects from a source project into the matching target project.

    CM / projectmerge.exe equivalent:
        projectmerge -f "PM_<project>_-_Integration2Freigabe.xml"
                     -sn Administrator -dn Administrator ...

    The merge uses these rules (mirroring the XML):
        Application objects  → Replace
        Configuration objects → UseExisting
        Schema objects        → Replace

    Args:
        source_conn:           Connection to the Integration (source) environment,
                               scoped to the source project.
        target_conn:           Connection to the Freigabe (target) environment.
        project_name:          Name of the project on both environments.
        migration_name_prefix: Prefix for the migration object name in MSTR.

    Returns True on success.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    migration_name = f"{migration_name_prefix} - {project_name} - {timestamp}"

    logger.info(
        f"  Starting ProjectMerge for '{project_name}': "
        f"Integration → Freigabe"
    )
    logger.info(f"  Migration name: '{migration_name}'")

    try:
        # ── Build the toc_view matching the XML rules ──────────────────────
        # Application  → Replace:     overwrite existing application objects
        # Configuration → UseExisting: keep current Freigabe configuration
        # Schema        → Replace:     overwrite schema objects (attributes, metrics …)
        toc_view = ProjectMergePackageTocView(
            application=Action.REPLACE,
            configuration=Action.USE_EXISTING,
            schema=Action.REPLACE,
        )

        # ── Create migration package on the source (Integration) ───────────
        logger.info("  Creating migration package on source (Integration)...")
        migration = Migration.create_project_merge_migration(
            connection=source_conn,
            toc_view=toc_view,
            name=migration_name,
            project_name=project_name,
        )
        logger.info(f"  Migration package created: ID='{migration.id}'")

        # ── Import (migrate) the package to the target (Freigabe) ─────────
        logger.info("  Importing migration package to target (Freigabe)...")
        migration.migrate(
            target_env=target_conn,
            target_project_name=project_name,
        )

        logger.info(
            f"  [OK] ProjectMerge completed for '{project_name}'"
        )
        return True

    except Exception as exc:
        logger.error(
            f"  [ERROR] ProjectMerge failed for '{project_name}': {exc}"
        )
        logger.debug(traceback.format_exc())
        return False
