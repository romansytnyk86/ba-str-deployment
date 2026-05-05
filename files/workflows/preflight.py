"""
workflows/preflight.py - Read-only validation before executing maintenance commands.

Checks
1. Connectivity to target and source environments
2. Project existence on target
3. Security role and group existence
4. DB connection existence
5. Merge project configuration validity
"""

import logging
from typing import Optional

from config import AppConfig
from mstr.connection import mstr_connection
from mstrio.access_and_security.security_role import SecurityRole
from mstrio.datasources import DatasourceConnection
from mstrio.server.project import Project
from mstrio.users_and_groups.user_group import UserGroup
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
    """Run read-only validation checks for config and connectivity."""
    errors: list[str] = []
    only_steps = only_steps or set()
    skip_steps = skip_steps or set()

    if _should_run_step(1, only_steps, skip_steps):
        if report:
            report.start_step(1, "connectivity")
        logger.info("")
        logger.info("[Preflight 1/5] Validate connectivity to target and source")
        try:
            with mstr_connection(cfg.mstr):
                logger.info("  [OK] Connected to target environment")
        except Exception as exc:
            logger.error(f"  [ERROR] Target connectivity failed: {exc}")
            errors.append("connect_target")

        try:
            with mstr_connection(cfg.source_mstr):
                logger.info("  [OK] Connected to source environment")
        except Exception as exc:
            logger.error(f"  [ERROR] Source connectivity failed: {exc}")
            errors.append("connect_source")
        if report:
            report.finish_step(1, success=not any(e.startswith("connect_") for e in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after check 1 failure.")
            return False
    else:
        if report:
            report.skip_step(1, "connectivity", "filtered by --only/--skip")

    if _should_run_step(2, only_steps, skip_steps):
        if report:
            report.start_step(2, "projects")
        logger.info("")
        logger.info("[Preflight 2/5] Validate project existence on target")
        try:
            with mstr_connection(cfg.mstr) as conn:
                for project_name in cfg.projects:
                    try:
                        _ = Project(conn, name=project_name)
                        logger.info(f"  [OK] Project found: '{project_name}'")
                    except Exception as exc:
                        logger.error(f"  [ERROR] Project missing/unavailable '{project_name}': {exc}")
                        errors.append(f"project({project_name})")
        except Exception as exc:
            logger.error(f"  [ERROR] Could not connect to target for project check: {exc}")
            errors.append("connect_target_step2")
        if report:
            report.finish_step(2, success=not any(e.startswith("project(") for e in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after check 2 failure.")
            return False
    else:
        if report:
            report.skip_step(2, "projects", "filtered by --only/--skip")

    if _should_run_step(3, only_steps, skip_steps):
        if report:
            report.start_step(3, "security")
        logger.info("")
        logger.info("[Preflight 3/5] Validate security role and group")
        try:
            with mstr_connection(cfg.mstr) as conn:
                try:
                    _ = SecurityRole(conn, name=cfg.security_role)
                    logger.info(f"  [OK] Security role found: '{cfg.security_role}'")
                except Exception as exc:
                    logger.error(f"  [ERROR] Security role not found '{cfg.security_role}': {exc}")
                    errors.append("security_role")

                try:
                    _ = UserGroup(conn, name=cfg.security_group)
                    logger.info(f"  [OK] Security group found: '{cfg.security_group}'")
                except Exception as exc:
                    logger.error(f"  [ERROR] Security group not found '{cfg.security_group}': {exc}")
                    errors.append("security_group")
        except Exception as exc:
            logger.error(f"  [ERROR] Could not connect to target for security check: {exc}")
            errors.append("connect_target_step3")
        if report:
            report.finish_step(3, success=("security_role" not in errors and "security_group" not in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after check 3 failure.")
            return False
    else:
        if report:
            report.skip_step(3, "security", "filtered by --only/--skip")

    if _should_run_step(4, only_steps, skip_steps):
        if report:
            report.start_step(4, "db_connections")
        logger.info("")
        logger.info("[Preflight 4/5] Validate DB connections in catalog change list")
        try:
            with mstr_connection(cfg.mstr) as conn:
                for connection_name, _new_catalog in cfg.db_catalog_changes:
                    try:
                        _ = DatasourceConnection(conn, name=connection_name)
                        logger.info(f"  [OK] DB connection found: '{connection_name}'")
                    except Exception as exc:
                        logger.error(f"  [ERROR] DB connection missing '{connection_name}': {exc}")
                        errors.append(f"db_connection({connection_name})")
        except Exception as exc:
            logger.error(f"  [ERROR] Could not connect to target for DB connection check: {exc}")
            errors.append("connect_target_step4")
        if report:
            report.finish_step(4, success=not any(e.startswith("db_connection(") for e in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after check 4 failure.")
            return False
    else:
        if report:
            report.skip_step(4, "db_connections", "filtered by --only/--skip")

    if _should_run_step(5, only_steps, skip_steps):
        if report:
            report.start_step(5, "merge_config")
        logger.info("")
        logger.info("[Preflight 5/5] Validate merge project configuration")
        unknown = [p for p in cfg.merge_projects if p not in cfg.projects]
        if unknown:
            logger.error(f"  [ERROR] MERGE_PROJECTS contains unknown project(s): {unknown}")
            errors.append("merge_projects")
        else:
            logger.info("  [OK] MERGE_PROJECTS is valid")
        if report:
            report.finish_step(5, success=("merge_projects" not in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after check 5 failure.")
            return False
    else:
        if report:
            report.skip_step(5, "merge_config", "filtered by --only/--skip")

    logger.info("")
    if errors:
        logger.error(f"[FAILED] preflight finished with {len(errors)} error(s): {', '.join(errors)}")
        return False

    logger.info("[SUCCESS] preflight completed successfully")
    return True
