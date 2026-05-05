"""
workflows/start_01.py — Phase 1: Revoke access, disconnect users, clear caches.

Replaces:
  CM_Start_Wartungsfenster_01.scp  — REVOKE SECURITY ROLE (all 6 projects)
  CM_Start_Wartungsfenster_02.scp  — DISCONNECT USER CONNECTIONS (all 6 projects)
                                   — DELETE/PURGE/DELETE CACHES (SGB II S2S Relational)

Run this script BEFORE the metadata database backup.
After it completes successfully, start the DB backup, then run start_02.

Steps
─────
  [Step 1/3] Revoke security role from all 6 projects
  [Step 2/3] Disconnect user connections from all 6 projects
  [Step 3/3] Clear caches for configured projects (default: SGB II S2S Relational)
"""

import logging
from typing import Optional

from config import AppConfig
from mstr.cache import clear_all_project_caches
from mstr.connection import mstr_connection
from mstr.project import disconnect_users
from mstr.security import revoke_security_role
from mstrio.server.project import Project
from utils.process_report import ProcessReport

logger = logging.getLogger("sgb2_freigabe")


def _should_run_step(step_id: int, only_steps: set[int], skip_steps: set[int]) -> bool:
    if only_steps and step_id not in only_steps:
        return False
    if step_id in skip_steps:
        return False
    return True


def run(
    cfg: AppConfig,
    only_steps: Optional[set[int]] = None,
    skip_steps: Optional[set[int]] = None,
    report: Optional[ProcessReport] = None,
) -> bool:
    """
    Execute Phase 1 of the maintenance window.
    Returns True if all steps succeeded without errors.
    """
    errors: list[str] = []
    only_steps = only_steps or set()
    skip_steps = skip_steps or set()

    # ── Step 1/3: Revoke security role ────────────────────────────────────────
    if _should_run_step(1, only_steps, skip_steps):
        if report:
            report.start_step(1, "revoke_security_role")
        logger.info("")
        logger.info("[Step 1/3] Revoke security role from all projects")
        logger.info(
            f"  Role: '{cfg.security_role}'  |  "
            f"Group: '{cfg.security_group}'  |  "
            f"Projects: {len(cfg.projects)}"
        )

        with mstr_connection(cfg.mstr) as conn:
            for project_name in cfg.projects:
                ok = revoke_security_role(
                    conn=conn,
                    role_name=cfg.security_role,
                    group_name=cfg.security_group,
                    project_name=project_name,
                )
                if not ok:
                    errors.append(f"revoke_security_role({project_name})")
        if report:
            report.finish_step(1, success=not any(e.startswith("revoke_security_role(") for e in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after step 1 failure.")
            return False
    else:
        if report:
            report.skip_step(1, "revoke_security_role", "filtered by --only/--skip")

    # ── Step 2/3: Disconnect user connections ─────────────────────────────────
    if _should_run_step(2, only_steps, skip_steps):
        if report:
            report.start_step(2, "disconnect_users")
        logger.info("")
        logger.info("[Step 2/3] Disconnect user connections from all projects")

        with mstr_connection(cfg.mstr) as conn:
            for project_name in cfg.projects:
                ok = disconnect_users(conn=conn, project_name=project_name)
                if not ok:
                    errors.append(f"disconnect_users({project_name})")
        if report:
            report.finish_step(2, success=not any(e.startswith("disconnect_users(") for e in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after step 2 failure.")
            return False
    else:
        if report:
            report.skip_step(2, "disconnect_users", "filtered by --only/--skip")

    # ── Step 3/3: Clear caches ────────────────────────────────────────────────
    if _should_run_step(3, only_steps, skip_steps):
        if report:
            report.start_step(3, "clear_caches")
        logger.info("")
        logger.info("[Step 3/3] Clear caches for configured projects")

        if not cfg.cache_clear_projects:
            logger.info("  No projects configured for cache clearing — skipping")
        else:
            with mstr_connection(cfg.mstr) as conn:
                for project_name in cfg.cache_clear_projects:
                    logger.info(f"  Clearing caches for '{project_name}'...")
                    try:
                        project = Project(connection=conn, name=project_name)
                        project_id = project.id
                    except Exception as exc:
                        logger.error(
                            f"  [ERROR] Could not look up project ID for "
                            f"'{project_name}': {exc}"
                        )
                        errors.append(f"project_lookup({project_name})")
                        continue

                    clear_all_project_caches(
                        conn=conn,
                        project_id=project_id,
                        project_name=project_name,
                    )
        if report:
            report.finish_step(3, success=not any(e.startswith("project_lookup(") for e in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after step 3 failure.")
            return False
    else:
        if report:
            report.skip_step(3, "clear_caches", "filtered by --only/--skip")

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("")
    if errors:
        logger.error(
            f"[FAILED] start_01 finished with {len(errors)} error(s): "
            + ", ".join(errors)
        )
        return False

    logger.info("[SUCCESS] start_01 completed successfully")
    logger.info("")
    logger.info("=" * 60)
    logger.info("  >>> NEXT STEP: Start the metadata database backup now. <<<")
    logger.info("  >>> After the backup is complete, run start_02.         <<<")
    logger.info("=" * 60)
    return True
