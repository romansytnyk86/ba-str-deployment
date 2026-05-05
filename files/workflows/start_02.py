"""
workflows/start_02.py — Phase 2: Unload, update DB, load, merge, schema, caches.

Replaces:
  CM_Start_Wartungsfenster_03.scp  — (optional: load projects, ObjectManager packages)
  CM_Start_Wartungsfenster_04.scp  — UNLOAD, ALTER DBCONNECTION, LOAD
  BAT ProjectMerge step            — projectmerge.exe Integration → Freigabe
  CM_Start_Wartungsfenster_05.scp  — UPDATE SCHEMA, DELETE/PURGE CACHES, LIST PROPS
  CM_Start_Wartungsfenster_06.scp  — LIST SERVER CONFIGURATION (informational, logged)

Run this script AFTER the metadata database backup (start_01 + DB backup done).

Steps
─────
  [Step 1/7] Unload all 6 projects (3 batches with configurable delays)
  [Step 2/7] Alter DB connection catalog strings (6 connections)
  [Step 3/7] Load all 6 projects (3 batches with configurable delays)
  [Step 4/7] ProjectMerge: Integration → Freigabe (only projects listed in MERGE_PROJECTS)
  [Step 5/7] Schema update for all 6 projects
  [Step 6/7] Clear caches for configured projects (default: SGB II S2S Relational)
  [Step 7/7] List DB connection properties and project settings (informational)
"""

import logging
import time
from typing import Optional

from config import AppConfig
from mstr.cache import clear_all_project_caches
from mstr.connection import mstr_connection
from mstr.dbconnection import alter_db_connection_catalog, list_db_connection_properties
from mstr.merge import project_merge
from mstr.project import load_project, unload_project
from mstr.schema import update_schema
from mstrio.server.project import Project
from utils.process_report import ProcessReport

logger = logging.getLogger("sgb2_freigabe")


def _project_batches(projects: list[str], size: int = 2) -> list[list[str]]:
    """Split projects into fixed-size batches while preserving order."""
    return [projects[i:i + size] for i in range(0, len(projects), size)]


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
    Execute Phase 2 of the maintenance window.
    Returns True if all steps succeeded without errors.
    """
    errors: list[str] = []
    only_steps = only_steps or set()
    skip_steps = skip_steps or set()
    projects = cfg.projects

    # ── Step 1/7: Unload projects in 3 batches ────────────────────────────────
    if _should_run_step(1, only_steps, skip_steps):
        if report:
            report.start_step(1, "unload_projects")
        logger.info("")
        logger.info("[Step 1/7] Unload all projects")
        logger.info(
            "  Batches mirror the original CM script: "
            "Batch1 (2p) -> sleep, Batch2 (2p) -> sleep, Batch3 (2p) -> sleep"
        )

        with mstr_connection(cfg.mstr) as conn:
            delays = [cfg.unload_batch1_delay, cfg.unload_batch2_delay, cfg.unload_batch3_delay]
            batches = _project_batches(projects, size=2)
            for idx, batch in enumerate(batches, start=1):
                for p in batch:
                    ok = unload_project(conn, p)
                    if not ok:
                        errors.append(f"unload({p})")
                wait_s = delays[min(idx - 1, len(delays) - 1)]
                logger.info(f"  Batch {idx} complete - waiting {wait_s}s...")
                time.sleep(wait_s)
        if report:
            report.finish_step(1, success=not any(e.startswith("unload(") for e in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after step 1 failure.")
            return False
    else:
        if report:
            report.skip_step(1, "unload_projects", "filtered by --only/--skip")

    # ── Step 2/7: Alter DB connection catalog strings ─────────────────────────
    if _should_run_step(2, only_steps, skip_steps):
        if report:
            report.start_step(2, "alter_db_connections")
        logger.info("")
        logger.info("[Step 2/7] Alter DB connection catalog strings")
        logger.info(f"  {len(cfg.db_catalog_changes)} connection(s) to update")

        with mstr_connection(cfg.mstr) as conn:
            for connection_name, new_catalog in cfg.db_catalog_changes:
                ok = alter_db_connection_catalog(
                    conn=conn,
                    connection_name=connection_name,
                    new_catalog=new_catalog,
                )
                if not ok:
                    errors.append(f"alter_db_connection({connection_name})")

        logger.info(
            f"  All DB connection changes applied - waiting {cfg.db_change_delay}s..."
        )
        time.sleep(cfg.db_change_delay)
        if report:
            report.finish_step(2, success=not any(e.startswith("alter_db_connection(") for e in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after step 2 failure.")
            return False
    else:
        if report:
            report.skip_step(2, "alter_db_connections", "filtered by --only/--skip")

    # ── Step 3/7: Load projects in 3 batches ──────────────────────────────────
    if _should_run_step(3, only_steps, skip_steps):
        if report:
            report.start_step(3, "load_projects")
        logger.info("")
        logger.info("[Step 3/7] Load all projects")

        with mstr_connection(cfg.mstr) as conn:
            batches = _project_batches(projects, size=2)
            for idx, batch in enumerate(batches, start=1):
                for p in batch:
                    ok = load_project(conn, p)
                    if not ok:
                        errors.append(f"load({p})")
                logger.info(f"  Batch {idx} complete - waiting {cfg.load_batch_delay}s...")
                time.sleep(cfg.load_batch_delay)
        if report:
            report.finish_step(3, success=not any(e.startswith("load(") for e in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after step 3 failure.")
            return False
    else:
        if report:
            report.skip_step(3, "load_projects", "filtered by --only/--skip")

    # ── Step 4/7: ProjectMerge Integration → Freigabe ─────────────────────────
    if _should_run_step(4, only_steps, skip_steps):
        if report:
            report.start_step(4, "project_merge")
        logger.info("")
        logger.info("[Step 4/7] ProjectMerge: Integration -> Freigabe")

        if not cfg.merge_projects:
            logger.info(
                "  MERGE_PROJECTS is empty - skipping all project merges. "
                "Add project names to deployment.env to enable."
            )
        else:
            logger.info(f"  Projects to merge: {cfg.merge_projects}")
            logger.info(
                "  Projects NOT in MERGE_PROJECTS are skipped (mirroring "
                "commented-out entries in the original BAT)."
            )
            with mstr_connection(cfg.mstr) as tgt_conn:
                for project_name in projects:
                    if project_name not in cfg.merge_projects:
                        logger.info(
                            f"  Skipping '{project_name}' (not in MERGE_PROJECTS)"
                        )
                        continue

                    with mstr_connection(cfg.source_mstr, project_name=project_name) as src_conn:
                        ok = project_merge(
                            source_conn=src_conn,
                            target_conn=tgt_conn,
                            project_name=project_name,
                            migration_name_prefix=cfg.merge_name_prefix,
                        )
                        if not ok:
                            errors.append(f"project_merge({project_name})")
        if report:
            report.finish_step(4, success=not any(e.startswith("project_merge(") for e in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after step 4 failure.")
            return False
    else:
        if report:
            report.skip_step(4, "project_merge", "filtered by --only/--skip")

    # ── Step 5/7: Schema update for all 6 projects ────────────────────────────
    if _should_run_step(5, only_steps, skip_steps):
        if report:
            report.start_step(5, "schema_update")
        logger.info("")
        logger.info("[Step 5/7] Schema update for all projects")

        with mstr_connection(cfg.mstr) as conn:
            for project_name in projects:
                logger.info(f"  Schema update: '{project_name}'")
                try:
                    project = Project(connection=conn, name=project_name)
                    project_id = project.id
                except Exception as exc:
                    logger.error(
                        f"  [ERROR] Could not resolve project ID for "
                        f"'{project_name}': {exc}"
                    )
                    errors.append(f"schema_project_lookup({project_name})")
                    continue

                with mstr_connection(cfg.mstr, project_name=project_name) as proj_conn:
                    ok = update_schema(conn=proj_conn, project_id=project_id)
                    if not ok:
                        errors.append(f"update_schema({project_name})")
        if report:
            schema_ok = not any(
                e.startswith("schema_project_lookup(") or e.startswith("update_schema(")
                for e in errors
            )
            report.finish_step(5, success=schema_ok)
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after step 5 failure.")
            return False
    else:
        if report:
            report.skip_step(5, "schema_update", "filtered by --only/--skip")

    # ── Step 6/7: Clear caches again ──────────────────────────────────────────
    if _should_run_step(6, only_steps, skip_steps):
        if report:
            report.start_step(6, "clear_caches")
        logger.info("")
        logger.info("[Step 6/7] Clear caches for configured projects (post-schema)")

        if not cfg.cache_clear_projects:
            logger.info("  No projects configured for cache clearing - skipping")
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
                        errors.append(f"cache_project_lookup({project_name})")
                        continue

                    clear_all_project_caches(
                        conn=conn,
                        project_id=project_id,
                        project_name=project_name,
                    )
        if report:
            report.finish_step(6, success=not any(e.startswith("cache_project_lookup(") for e in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after step 6 failure.")
            return False
    else:
        if report:
            report.skip_step(6, "clear_caches", "filtered by --only/--skip")

    # ── Step 7/7: List DB connection properties (informational) ───────────────
    if _should_run_step(7, only_steps, skip_steps):
        if report:
            report.start_step(7, "list_properties")
        logger.info("")
        logger.info("[Step 7/7] List DB connection properties (informational)")

        if not cfg.db_connections_to_list:
            logger.info("  No DB connections configured for listing - skipping")
        else:
            with mstr_connection(cfg.mstr) as conn:
                for connection_name in cfg.db_connections_to_list:
                    list_db_connection_properties(conn=conn, connection_name=connection_name)

            logger.info("  Project configuration properties are visible in the")
            logger.info("  MicroStrategy Web Administrator portal under each project.")
        if report:
            report.finish_step(7, success=True)
    else:
        if report:
            report.skip_step(7, "list_properties", "filtered by --only/--skip")

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("")
    if errors:
        logger.error(
            f"[FAILED] start_02 finished with {len(errors)} error(s): "
            + ", ".join(errors)
        )
        return False

    logger.info("[SUCCESS] start_02 completed successfully")
    logger.info("")
    logger.info("=" * 60)
    logger.info("  >>> Maintenance window active. Run 'ende' when done. <<<")
    logger.info("=" * 60)
    return True
