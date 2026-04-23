"""
workflows/deployment_with_backup_duplication.py - Deployment WITH project backup duplication (nach PD).

Replaces: BAT_SGB_II_MaEnde_D2D.BAT + CM_SGB_II_MaEnde_nach_PD.scp
          + ProjectDuplicate.exe + D_SGB_II_MaEnde_D2D.xml

When to use:
    Use this at the start of a new deployment cycle when you want to keep
    a snapshot of the current project before redeploying (e.g. month-end).
    The backup project gets all user access removed so end users cannot
    accidentally open it.

    Command: python main.py mit-backup --backup-month 202512 [--env deployment.env]
    The --backup-month value is appended to BACKUP_PROJECT_BASE_NAME, e.g.:
        "SGB II MaEnde" + "202512" -> "SGB II MaEnde 202512"

Backup method is controlled by BACKUP_METHOD in deployment.env ("duplicate", "merge", or "package").

Steps:
    1. Disconnect all active users from the main project
    2. Create a backup project (duplicate or merge, based on BACKUP_METHOD)
    3. Unload the main project
    4. Update the DB connection catalog on the main project
    5. Reload the main project
    6. Load the backup project
    7. Revoke all user access from the backup project

Settings used from deployment.env:
    MSTR_PROJECT_NAME           - the main project to redeploy
    BACKUP_PROJECT_BASE_NAME    - base name for the backup project
    DB_CONNECTION_NAME          - which datasource connection to update
    DB_CATALOG_NAME             - the new catalog name to set
    REVOKE_ROLE_GROUP_PAIRS     - which role/group access to remove from backup
"""

import logging
import time
import traceback
from datetime import datetime
from typing import Optional
from config import AppConfig, MstrConfig
from mstrio.server.project import CrossDuplicationConfig, Project, ProjectDuplication

from mstr import (
    mstr_connection,
    disconnect_users,
    unload_project,
    create_backup_project,
    alter_db_connection_catalog,
    load_project,
    revoke_security_role,
    update_schema,
)

logger = logging.getLogger("sgb2_maende")

_CROSS_ENV_POLL_INTERVAL_S = 30
_CROSS_ENV_MAX_RETRIES = 5


def _poll_cross_env_duplication(job: ProjectDuplication, timeout_min: int = 60) -> bool:
    """
    Poll a cross-environment duplication job until completion.

    `wait_for_stable_status()` loses the source session during cross-env ops
    and raises ERR001. This replacement tolerates transient fetch failures.
    """
    timeout_s = timeout_min * 60
    start = time.time()
    consecutive_errors = 0

    logger.info(f"  Polling job {job.id} (timeout: {timeout_min} min, retry-tolerant)...")

    while time.time() - start < timeout_s:
        try:
            job.fetch()
            consecutive_errors = 0
        except Exception as exc:
            consecutive_errors += 1
            logger.warning(f"    [WARN] Status fetch failed ({consecutive_errors}/{_CROSS_ENV_MAX_RETRIES}): {exc}")
            if consecutive_errors >= _CROSS_ENV_MAX_RETRIES:
                logger.error("  [ERROR] Too many consecutive fetch failures — aborting poll")
                return False
            time.sleep(_CROSS_ENV_POLL_INTERVAL_S)
            continue

        elapsed = int(time.time() - start)
        status_str = str(job.status).upper()
        progress = getattr(job, "progress", None)
        progress_s = f" | {progress}%" if progress is not None else ""
        logger.info(f"    [{elapsed:>4}s] {job.status}{progress_s}")

        if "COMPLETE" in status_str:
            logger.info(f"  Cross-environment duplication completed successfully after {elapsed}s")
            return True
        if "FAILED" in status_str or "CANCEL" in status_str:
            msg = getattr(job, "message", "")
            logger.error(f"  [ERROR] Duplication ended: {job.status}" + (f" | {msg}" if msg else ""))
            return False

        time.sleep(_CROSS_ENV_POLL_INTERVAL_S)

    logger.error(f"  [ERROR] Timeout after {timeout_min} minutes")
    return False


def run(cfg: AppConfig, backup_month: str, target_mstr: Optional[MstrConfig] = None) -> bool:
    """
    Execute the with-backup deployment workflow.

    Args:
        cfg:          All settings loaded from deployment.env
        backup_month: The month suffix passed via --backup-month (e.g. "202512")
        target_mstr:  Optional target environment credentials for cross-environment duplication.

    Returns True if all steps succeeded, False if any step failed.
    """
    project = cfg.project.project_name
    backup_project = f"{cfg.project.backup_base_name} {backup_month}"
    steps_ok = []
    start = datetime.now()

    logger.info("")
    logger.info("=" * 60)
    logger.info("  WORKFLOW: mit Backup (with backup / nach PD)")
    logger.info(f"  Project:        {project}")
    logger.info(f"  Backup project: {backup_project}")
    logger.info(f"  Server:         {cfg.mstr.base_url}")
    if target_mstr:
        logger.info(f"  Target server:  {target_mstr.base_url}")
        logger.info(f"  Target user:    {target_mstr.username}")
    logger.info("=" * 60)

    if target_mstr:
        with mstr_connection(cfg.mstr) as source_conn, mstr_connection(target_mstr) as target_conn:

            # ── Step 1: Disconnect users on source environment ──────────
            logger.info("\n[Step 1/5] Disconnect user connections on source environment")
            ok = disconnect_users(source_conn, project)
            steps_ok.append(("Disconnect users", ok))
            if not ok:
                logger.error("  Aborting workflow due to step failure.")
                return _summary(steps_ok, start)

            # ── Step 2: Create backup on target environment ───────────────
            if cfg.project.backup_method == "duplicate":
                logger.info(f"\n[Step 2/5] Duplicate project from {cfg.mstr.base_url} to {target_mstr.base_url}")
                try:
                    source_project = Project(source_conn, name=project)
                    duplication_config = CrossDuplicationConfig(
                        match_users_by_login=cfg.project.duplicate_match_users_by_login
                    )
                    job = source_project.duplicate_to_other_environment(
                        target_name=backup_project,
                        target_env=target_conn,
                        cross_duplication_config=duplication_config,
                        sync_with_target_env=cfg.project.duplicate_sync_with_target_environment,
                    )
                    logger.info(f"  Job ID: {job.id} | Initial status: {job.status}")
                    ok = _poll_cross_env_duplication(job)
                    
                    steps_ok.append(("Duplicate to target environment", ok))
                    if not ok:
                        logger.error("  Aborting workflow due to step failure.")
                        return _summary(steps_ok, start)
                except Exception as exc:
                    error_str = str(exc)
                    logger.error(f"  [ERROR] Cross-environment duplication failed: {exc}")
                    if "ERR001" in error_str and "duplication status" in error_str.lower():
                        logger.error("")
                        logger.error("  [DIAGNOSTIC] StorageService is likely not configured between the two environments.")
                        logger.error("  To fix: configure a shared Storage Service location on both source and target")
                        logger.error("  environments (Administration > Storage Service > Settings), then re-run.")
                    logger.debug(traceback.format_exc())
                    steps_ok.append(("Duplicate to target environment", False))
                    return _summary(steps_ok, start)
            elif cfg.project.backup_method == "package":
                logger.info(f"\n[Step 2/5] Create project package from {cfg.mstr.base_url} and restore on {target_mstr.base_url}")
                try:
                    source_project = Project(source_conn, name=project)
                    # sync_with_target_env=False triggers source-side package creation only
                    # (no shared StorageService required). The package is then restored
                    # on the target environment in a second step.
                    job = source_project.duplicate_to_other_environment(
                        target_name=backup_project,
                        target_env=target_conn,
                        cross_duplication_config=CrossDuplicationConfig(
                            match_users_by_login=cfg.project.duplicate_match_users_by_login
                        ),
                        sync_with_target_env=False,
                    )
                    logger.info(f"  Source job ID: {job.id} | Initial status: {job.status}")
                    ok = _poll_cross_env_duplication(job)
                    if ok:
                        logger.info("  Restoring package on target environment...")
                        target_job = job.restore_package_on_target_environment(
                            target_env=target_conn
                        )
                        logger.info(f"  Target job ID: {target_job.id} | Initial status: {target_job.status}")
                        ok = _poll_cross_env_duplication(target_job)
                    steps_ok.append(("Create project package and restore on target environment", ok))
                    if not ok:
                        logger.error("  Aborting workflow due to step failure.")
                        return _summary(steps_ok, start)
                except Exception as exc:
                    logger.error(f"  [ERROR] Project package migration failed: {exc}")
                    logger.debug(traceback.format_exc())
                    steps_ok.append(("Create project package and restore on target environment", False))
                    return _summary(steps_ok, start)
            else:
                logger.error(f"  [ERROR] Unsupported BACKUP_METHOD for cross-environment: {cfg.project.backup_method}")
                steps_ok.append(("Create backup on target environment", False))
                return _summary(steps_ok, start)

            # ── Step 3: Load backup project on target environment ──────
            logger.info("\n[Step 3/5] Load backup project on target environment")
            ok = load_project(target_conn, backup_project)
            steps_ok.append(("Load backup project on target environment", ok))
            if not ok:
                logger.error("  Aborting workflow due to step failure.")
                return _summary(steps_ok, start)

            # ── Step 4: Revoke security roles on target environment ───
            logger.info("\n[Step 4/5] Revoke security roles from backup project on target environment")
            if not cfg.project.revoke_role_group_pairs:
                logger.warning("  [WARN] REVOKE_ROLE_GROUP_PAIRS is empty in deployment.env — skipping")
                steps_ok.append(("Revoke security roles", True))
            else:
                all_revoked = True
                for role_name, group_name in cfg.project.revoke_role_group_pairs:
                    ok = revoke_security_role(target_conn, role_name, group_name, backup_project)
                    if not ok:
                        all_revoked = False
                steps_ok.append(("Revoke security roles", all_revoked))
                if not all_revoked:
                    logger.error("  Aborting workflow due to step failure.")
                    return _summary(steps_ok, start)

        return _summary(steps_ok, start)

    with mstr_connection(cfg.mstr) as conn:

        # Ensure the main project is loaded before starting operations
        try:
            proj = Project(conn, name=project)
            if proj.status != 'loaded':
                logger.info(f"  Project '{project}' is not loaded. Loading it...")
                load_project(conn, project)
        except Exception as exc:
            logger.warning(f"  Could not check/load project status: {exc} — proceeding anyway")

        # ── Step 1: Disconnect users ──────────────────────────────────
        # Kicks all active user sessions off the project so it can be unloaded.
        # Admin/service sessions that cannot be disconnected are expected
        # and reported as warnings — they do not cause a failure.
        logger.info("\n[Step 1/7] Disconnect user connections")
        ok = disconnect_users(conn, project)
        steps_ok.append(("Disconnect users", ok))
        if not ok:
            logger.error("  Aborting workflow due to step failure.")
            return _summary(steps_ok, start)

        # ── Step 2: Create backup project ─────────────────
        # Creates a full copy of the main project named e.g. "SGB II MaEnde 202512".
        # This is an async server-side operation that is polled until complete.
        # Replaces: ProjectDuplicate.exe + D_SGB_II_MaEnde_D2D.xml
        if cfg.project.backup_method == "package":
            logger.error(
                "  [ERROR] BACKUP_METHOD='package' is not supported for same-environment mit-backup."
                " Use a target environment or set BACKUP_METHOD='duplicate'."
            )
            steps_ok.append(("Create backup project", False))
            return _summary(steps_ok, start)

        logger.info("\n[Step 2/7] Create backup project")
        ok = create_backup_project(
            conn,
            source_project_name=project,
            target_project_name=backup_project,
            method=cfg.project.backup_method,
            description=f"Backup of '{project}' ({backup_month})",
        )
        steps_ok.append(("Create backup project", ok))
        if not ok:
            logger.error("  Aborting workflow due to step failure.")
            return _summary(steps_ok, start)

        # ── Step 3: Unload main project ───────────────────────────────
        # Takes the project offline. Required before updating the DB connection.
        logger.info("\n[Step 3/7] Unload main and backup projects")
        ok_main = unload_project(conn, project)
        ok_backup = unload_project(conn, backup_project)
        ok = ok_main and ok_backup
        steps_ok.append(("Unload main and backup projects", ok))
        if not ok:
            logger.error("  Aborting workflow due to step failure.")
            return _summary(steps_ok, start)

        # ── Step 4: Alter DB connection catalog ───────────────────────
        # Updates the CATALOG in the datasource connection string on the main project.
        # Equivalent to: ALTER DBCONNECTION "..." CATALOG "..."
        # Values come from DB_CONNECTION_NAME and DB_CATALOG_NAME in deployment.env
        if cfg.enable_db_catalog_change:
            logger.info("\n[Step 4/7] Alter DB connection catalog")
            ok = alter_db_connection_catalog(
                conn,
                connection_name=cfg.project.db_connection_name,
                new_catalog=cfg.project.db_catalog_name,
            )
            steps_ok.append(("Alter DB connection", ok))
            if not ok:
                logger.error("  Aborting workflow due to step failure.")
                return _summary(steps_ok, start)
        else:
            logger.info("\n[Step 4/7] Skip altering DB connection catalog (disabled in config)")
            steps_ok.append(("Alter DB connection", True))  # Mark as skipped but successful

        # ── Step 5: Load main project ─────────────────────────────────
        # Brings the main project back online for end users.
        logger.info("\n[Step 5/7] Load main project")
        ok = load_project(conn, project)
        steps_ok.append(("Load main project", ok))
        if not ok:
            logger.error("  Aborting workflow due to step failure.")
            return _summary(steps_ok, start)

        # ── Step 6: Load backup project ───────────────────────────────
        # Loads the newly created backup project so security roles can be revoked.
        # After Step 7 it will be inaccessible to regular users.
        logger.info("\n[Step 6/8] Load backup project")
        ok = load_project(conn, backup_project)
        steps_ok.append(("Load backup project", ok))
        if not ok:
            logger.error("  Aborting workflow due to step failure.")
            return _summary(steps_ok, start)

        # ── Step 7: Update schemas ───────────────────────────────────
        if cfg.enable_schema_update:
            logger.info("\n[Step 7a/8] Update schema for main project")
            ok = update_schema(conn, cfg.project.project_id)
            steps_ok.append(("Update schema main", ok))
            if not ok:
                logger.error("  Aborting workflow due to step failure.")
                return _summary(steps_ok, start)

            logger.info("\n[Step 7b/8] Update schema for backup project")
            backup_proj = Project(conn, name=backup_project)
            ok = update_schema(conn, backup_proj.id)
            steps_ok.append(("Update schema backup", ok))
            if not ok:
                logger.error("  Aborting workflow due to step failure.")
                return _summary(steps_ok, start)
        else:
            logger.info("\n[Step 7/8] Skip schema updates (disabled in config)")
            steps_ok.append(("Update schemas", True))

    # ── Step 8: Revoke security roles from backup project ─────────
    # Done outside the main connection context to avoid session timeout issues.
    # Removes all user group access from the backup project so end users
    # cannot accidentally connect to it.
    # Pairs to revoke come from REVOKE_ROLE_GROUP_PAIRS in deployment.env.
    # Equivalent to: REVOKE SECURITY ROLE "..." FROM GROUP "..." FROM PROJECT "..."
    if cfg.enable_security_role_revocation:
        logger.info("\n[Step 8/8] Revoke security roles from backup project")
        if not cfg.project.revoke_role_group_pairs:
            logger.warning("  [WARN] REVOKE_ROLE_GROUP_PAIRS is empty in deployment.env — skipping")
            steps_ok.append(("Revoke security roles", True))
        else:
            all_revoked = True
            with mstr_connection(cfg.mstr) as revoke_conn:
                for role_name, group_name in cfg.project.revoke_role_group_pairs:
                    ok = revoke_security_role(revoke_conn, role_name, group_name, backup_project)
                    if not ok:
                        all_revoked = False
            steps_ok.append(("Revoke security roles", all_revoked))
    else:
        logger.info("\n[Step 8/8] Skip revoking security roles (disabled in config)")
        steps_ok.append(("Revoke security roles", True))

    return _summary(steps_ok, start)


def _summary(steps_ok: list, start: datetime) -> bool:
    """Print a result table for each step, elapsed time, and return overall success."""
    duration = str(datetime.now() - start).split(".")[0]  # strip microseconds
    logger.info("")
    logger.info("=" * 60)
    logger.info("  WORKFLOW SUMMARY")
    logger.info("=" * 60)
    all_ok = True
    for step_name, result in steps_ok:
        status = "[OK]   " if result else "[FAIL]"
        logger.info(f"  {status} {step_name}")
        if not result:
            all_ok = False
    logger.info(f"\n  Duration: {duration}")
    if all_ok:
        logger.info("  [SUCCESS] Workflow completed successfully")
    else:
        logger.error("  [FAILED] Workflow completed with errors")
    logger.info("=" * 60)
    return all_ok
