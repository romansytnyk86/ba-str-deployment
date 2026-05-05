"""
workflows/ende.py — Phase 3: Restore user access (end of maintenance window).

Replaces:
  CM_Ende_Wartungsfenster_01.scp — LOAD all 6 projects (safety)
                                  — GRANT SECURITY ROLE to all 6 projects

Steps
─────
  [Step 1/2] Load all 6 projects (safety — roles cannot be granted to unloaded projects)
  [Step 2/2] Grant security role to all 6 projects
"""

import logging
from typing import Optional

from config import AppConfig
from mstr.connection import mstr_connection
from mstr.project import load_project
from mstr.security import grant_security_role
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
    Execute Phase 3 of the maintenance window (end).
    Returns True if all steps succeeded without errors.
    """
    errors: list[str] = []
    only_steps = only_steps or set()
    skip_steps = skip_steps or set()

    # ── Step 1/2: Load all projects (safety) ──────────────────────────────────
    if _should_run_step(1, only_steps, skip_steps):
        if report:
            report.start_step(1, "load_projects")
        logger.info("")
        logger.info("[Step 1/2] Load all projects (safety check before granting access)")
        logger.info(
            "  Projects are loaded first to ensure security roles can be granted. "
            "Roles cannot be assigned to unloaded projects."
        )

        with mstr_connection(cfg.mstr) as conn:
            for project_name in cfg.projects:
                ok = load_project(conn=conn, project_name=project_name)
                if not ok:
                    errors.append(f"load({project_name})")
        if report:
            report.finish_step(1, success=not any(e.startswith("load(") for e in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after step 1 failure.")
            return False
    else:
        if report:
            report.skip_step(1, "load_projects", "filtered by --only/--skip")

    # ── Step 2/2: Grant security role ─────────────────────────────────────────
    if _should_run_step(2, only_steps, skip_steps):
        if report:
            report.start_step(2, "grant_security_role")
        logger.info("")
        logger.info("[Step 2/2] Grant security role to all projects")
        logger.info(
            f"  Role: '{cfg.security_role}'  |  "
            f"Group: '{cfg.security_group}'  |  "
            f"Projects: {len(cfg.projects)}"
        )

        with mstr_connection(cfg.mstr) as conn:
            for project_name in cfg.projects:
                ok = grant_security_role(
                    conn=conn,
                    role_name=cfg.security_role,
                    group_name=cfg.security_group,
                    project_name=project_name,
                )
                if not ok:
                    errors.append(f"grant_security_role({project_name})")
        if report:
            report.finish_step(2, success=not any(e.startswith("grant_security_role(") for e in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after step 2 failure.")
            return False
    else:
        if report:
            report.skip_step(2, "grant_security_role", "filtered by --only/--skip")

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("")
    if errors:
        logger.error(
            f"[FAILED] ende finished with {len(errors)} error(s): "
            + ", ".join(errors)
        )
        return False

    logger.info("[SUCCESS] ende completed successfully")
    logger.info("")
    logger.info("=" * 60)
    logger.info("  >>> Maintenance window CLOSED. User access restored. <<<")
    logger.info("=" * 60)
    return True
