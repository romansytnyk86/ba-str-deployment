#!/usr/bin/env python3
"""
main.py - Strategy Deployment Tool.

A general-purpose tool for deploying Strategy projects with or without backups.

Workflow is controlled by CREATE_BACKUP flag in deployment.env:
- CREATE_BACKUP=false: Deployment without backup
- CREATE_BACKUP=true:  Deployment with backup

Usage
-----
python main.py [--env FILE] [--backup-month YYYYMM] [--dry-run]
"""

import argparse
import sys
import os
from datetime import datetime
from typing import Optional

# Ensure all modules (config, utils, mstr, workflows) are findable
# regardless of which directory Python is launched from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config, MstrConfig
from utils.logger import setup_logger
from utils.logger import log_run_footer
from routing import (
    get_route,
    get_env_config,
    describe_routing_matrix,
    WORKFLOW_WITHOUT_BACKUP,
    WORKFLOW_BACKUP_DUPLICATE,
    WORKFLOW_VERSORGUNG_MERGE,
    WORKFLOW_BACKUP_DUPLICATE_THEN_VERSORGUNG_MERGE,
)
import workflows.deploy_without_backup as workflow_ohne
import workflows.deploy_with_backup_duplicate as workflow_mit
import workflows.deploy_with_backup_merge as workflow_merge


LOCK_FILE = ".deployment_lock"


def acquire_lock() -> bool:
    """
    Create a lock file to prevent concurrent deployments.
    Returns True if lock acquired, False if already locked.
    """
    if os.path.exists(LOCK_FILE):
        print(f"ERROR: Deployment already in progress (lock file {LOCK_FILE} exists).")
        print("Wait for the current deployment to complete or remove the lock file if it's stale.")
        return False
    try:
        with open(LOCK_FILE, 'w') as f:
            f.write(f"Locked at {datetime.now()}\n")
        return True
    except Exception as e:
        print(f"ERROR: Failed to create lock file: {e}")
        return False


def release_lock():
    """Remove the lock file."""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception as e:
        print(f"WARNING: Failed to remove lock file: {e}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sgb2_maende",
        description="Strategy deployment tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py
  python main.py --env deployment.local.env
  python main.py --backup-month 202512
  python main.py --backup-month 202512 --env deployment.customer.env
  python main.py --backup-month 202512 --target-base-url http://10.146.13.45:8080/MicroStrategyLibrary/ --target-username admin --target-password secret

  # Preview steps without connecting:
  python main.py --dry-run
  python main.py --backup-month 202512 --dry-run
        """,
    )

    parser.add_argument(
        "--env",
        metavar="FILE",
        default="deployment.env",
        help="Credentials file (default: deployment.env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned steps without connecting to Strategy",
    )
    parser.add_argument(
        "--backup-month",
        metavar="YYYYMM",
        help="Month suffix for backup project name (overrides BACKUP_MONTH in config)",
    )
    parser.add_argument(
        "--target-base-url",
        metavar="URL",
        help="Target environment base URL for cross-environment duplication",
    )
    parser.add_argument(
        "--target-username",
        metavar="USER",
        help="Target environment username for cross-environment duplication",
    )
    parser.add_argument(
        "--target-password",
        metavar="PASS",
        help="Target environment password for cross-environment duplication",
    )
    parser.add_argument(
        "--target-login-mode",
        metavar="MODE",
        type=int,
        default=1,
        help="Target environment login mode (default: 1)",
    )

    # ── Routing-based invocation (Quelle/Ziel-Matrix) ─────────────────────
    routing_group = parser.add_argument_group(
        "Umgebungsrouting (Quelle/Ziel)",
        description=(
            "Alternativ zu --env und --create-backup: Quelle und Ziel angeben. "
            "Der korrekte Workflow wird automatisch aus der Routing-Matrix gewählt. "
            "Beispiel: --source-env Design --target-env Integration --backup-month 202604"
        ),
    )
    routing_group.add_argument(
        "--source-env",
        metavar="ENV",
        help=(
            "Quell-Umgebung (z. B. Design, Integration). "
            "Muss zusammen mit --target-env angegeben werden."
        ),
    )
    routing_group.add_argument(
        "--target-env",
        metavar="ENV",
        help=(
            "Ziel-Umgebung (z. B. Abnahme, Freigabe, Bereitstellung). "
            "Muss zusammen mit --source-env angegeben werden."
        ),
    )
    routing_group.add_argument(
        "--show-routes",
        action="store_true",
        help="Zeigt alle definierten Routen der Routing-Matrix an und beendet das Programm.",
    )

    return parser


def print_dry_run_ohne(cfg) -> None:
    print("\n[DRY RUN] ohne-backup workflow")
    print("-" * 56)
    print(f"  Server:  {cfg.mstr.base_url}")
    print(f"  User:    {cfg.mstr.username}")
    print(f"  Project: {cfg.project.project_name}")
    print()
    print("  Steps that would be executed:")
    print(f"    1. Disconnect users from '{cfg.project.project_name}'")
    print(f"    2. Unload '{cfg.project.project_name}'")
    if cfg.enable_db_catalog_change:
        print(f"    3. Alter DB connection '{cfg.project.db_connection_name}'"
              f" -> catalog '{cfg.project.db_catalog_name}'")
        print(f"    4. Load '{cfg.project.project_name}'")
    else:
        print("    3. Skip altering DB connection catalog (disabled in config)")
        print(f"    4. Load '{cfg.project.project_name}'")
    if cfg.enable_schema_update:
        print(f"    5. Update schema for '{cfg.project.project_name}'")
    else:
        print("    5. Skip schema update (disabled in config)")
    print("-" * 56)


def print_dry_run_mit(cfg, backup_month: str, target_mstr: Optional[MstrConfig] = None) -> None:
    backup_project = f"{cfg.project.backup_base_name} {backup_month}"
    if target_mstr:
        print("\n[DRY RUN] mit-backup workflow (cross-environment)")
    else:
        print("\n[DRY RUN] mit-backup workflow")
    print("-" * 56)
    print(f"  Source server:         {cfg.mstr.base_url}")
    print(f"  Source user:           {cfg.mstr.username}")
    if target_mstr:
        print(f"  Target server:         {target_mstr.base_url}")
        print(f"  Target user:           {target_mstr.username}")
    print(f"  Project:               {cfg.project.project_name}")
    print(f"  Backup project:        {backup_project}")
    print()
    print("  Steps that would be executed:")
    print(f"    1. Disconnect users from '{cfg.project.project_name}' on source environment")
    if target_mstr:
        method_desc = {
            "duplicate": f"Duplicate '{cfg.project.project_name}' to target environment as '{backup_project}'",
            "merge": f"Merge '{cfg.project.project_name}' to target environment as '{backup_project}' (NOT YET IMPLEMENTED)",
            "package": f"Create package from '{cfg.project.project_name}' and migrate to target environment as '{backup_project}'"
        }.get(cfg.project.backup_method, f"Unknown method '{cfg.project.backup_method}' for '{cfg.project.project_name}' to target environment")
        print(f"    2. {method_desc}")
        print(f"    3. Load '{backup_project}' on target environment")
        if cfg.project.revoke_role_group_pairs:
            for i, (role, group) in enumerate(cfg.project.revoke_role_group_pairs, 4):
                print(f"    {i}. Revoke '{role}' from '{group}' in '{backup_project}' on target environment")
    else:
        if cfg.project.backup_method == "package":
            print("    2. BACKUP_METHOD='package' is not supported for same-environment mit-backup.")
            print("    3. Provide a target environment or set BACKUP_METHOD='duplicate'.")
        else:
            print(f"    2. Duplicate '{cfg.project.project_name}' -> '{backup_project}'")
            print(f"    3. Unload '{cfg.project.project_name}'")
            print(f"    4. Unload '{backup_project}'")
        if cfg.enable_db_catalog_change:
            print(f"    5. Alter DB connection '{cfg.project.db_connection_name}' -> catalog '{cfg.project.db_catalog_name}'")
            print(f"    6. Load '{cfg.project.project_name}'")
            print(f"    7. Load '{backup_project}'")
            if cfg.enable_schema_update:
                print(f"    8. Update schemas for '{cfg.project.project_name}' and '{backup_project}'")
                if cfg.enable_security_role_revocation and cfg.project.revoke_role_group_pairs:
                    for i, (role, group) in enumerate(cfg.project.revoke_role_group_pairs, 9):
                        print(f"    {i}. Revoke '{role}' from '{group}' in '{backup_project}'")
                else:
                    print("    9. Skip revoking security roles (disabled in config)")
            else:
                print("    8. Skip schema updates (disabled in config)")
                if cfg.enable_security_role_revocation and cfg.project.revoke_role_group_pairs:
                    for i, (role, group) in enumerate(cfg.project.revoke_role_group_pairs, 9):
                        print(f"    {i}. Revoke '{role}' from '{group}' in '{backup_project}'")
                else:
                    print("    9. Skip revoking security roles (disabled in config)")
        else:
            print("    5. Skip altering DB connection catalog (disabled in config)")
            print(f"    6. Load '{cfg.project.project_name}'")
            print(f"    7. Load '{backup_project}'")
            if cfg.enable_schema_update:
                print(f"    8. Update schemas for '{cfg.project.project_name}' and '{backup_project}'")
                if cfg.enable_security_role_revocation and cfg.project.revoke_role_group_pairs:
                    for i, (role, group) in enumerate(cfg.project.revoke_role_group_pairs, 9):
                        print(f"    {i}. Revoke '{role}' from '{group}' in '{backup_project}'")
                else:
                    print("    9. Skip revoking security roles (disabled in config)")
            else:
                print("    8. Skip schema updates (disabled in config)")
                if cfg.enable_security_role_revocation and cfg.project.revoke_role_group_pairs:
                    for i, (role, group) in enumerate(cfg.project.revoke_role_group_pairs, 9):
                        print(f"    {i}. Revoke '{role}' from '{group}' in '{backup_project}'")
                else:
                    print("    9. Skip revoking security roles (disabled in config)")
    print("-" * 56)


def print_dry_run_merge(cfg, backup_month: str) -> None:
    backup_project = f"{cfg.project.backup_base_name} {backup_month}"
    print("\n[DRY RUN] mit-backup-merge workflow")
    print("-" * 56)
    print(f"  Server:         {cfg.mstr.base_url}")
    print(f"  User:           {cfg.mstr.username}")
    print(f"  Project:        {cfg.project.project_name}")
    print(f"  Backup project: {backup_project}")
    print()
    print("  Steps that would be executed:")
    print(f"    1. Disconnect users from '{cfg.project.project_name}'")
    print(f"    2. Merge '{cfg.project.project_name}' -> '{backup_project}' (NOT YET IMPLEMENTED)")
    print(f"    3. Unload '{cfg.project.project_name}'")
    print(f"    4. Alter DB connection '{cfg.project.db_connection_name}'"
          f" -> catalog '{cfg.project.db_catalog_name}'")
    print(f"    5. Load '{cfg.project.project_name}'")
    print(f"    6. Load '{backup_project}'")
    for i, (role, group) in enumerate(cfg.project.revoke_role_group_pairs, 7):
        print(f"    {i}. Revoke '{role}' from '{group}' in '{backup_project}'")
    print("-" * 56)


def _run_routing(args, parser) -> int:
    """
    Route-basierter Ausführungspfad: Quell- und Ziel-Umgebung sind bekannt.

    Lädt die Konfigurationsdateien beider Umgebungen, ermittelt den Workflow
    aus der Routing-Matrix und führt ihn aus — inklusive Dry-Run-Unterstützung.
    """
    try:
        route = get_route(args.source_env, args.target_env)
        source_env_cfg = get_env_config(args.source_env)
        target_env_cfg = get_env_config(args.target_env)
    except ValueError as exc:
        parser.error(str(exc))

    # Backup-Monat validieren
    backup_month = args.backup_month
    if route.backup_month_required and not backup_month:
        parser.error(
            f"Route '{args.source_env} → {args.target_env}' erfordert --backup-month "
            f"(z. B. --backup-month 202604)."
        )

    # Quell-Konfiguration laden
    cfg = load_config(env_file=source_env_cfg.env_file)

    # Ziel-Konfiguration laden (nur Verbindungsdaten werden verwendet)
    is_cross_env = args.source_env.lower() != args.target_env.lower()
    target_cfg = None
    if is_cross_env:
        target_cfg = load_config(env_file=target_env_cfg.env_file)
        cfg.target_mstr = target_cfg.mstr

    # Überschreibe backup_month aus Kommandozeile falls angegeben
    if backup_month:
        cfg.backup_month = backup_month

    command = f"{args.source_env}→{args.target_env}"
    logger = setup_logger(cfg.log.log_dir, cfg.log.log_file_name, command=command)

    logger.info("")
    logger.info("#" * 60)
    logger.info("  Strategy Deployment Tool  [Umgebungsrouting]")
    logger.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  Quelle:   {args.source_env}  ({source_env_cfg.description})")
    logger.info(f"  Ziel:     {args.target_env}  ({target_env_cfg.description})")
    logger.info(f"  Route:    {route.description}")
    logger.info(f"  Workflow: {route.workflow}")
    logger.info(f"  Server:   {cfg.mstr.base_url}")
    if is_cross_env and cfg.target_mstr:
        logger.info(f"  Ziel-Srv: {cfg.target_mstr.base_url}")
    if backup_month:
        logger.info(f"  Backup:   {cfg.project.backup_base_name} {backup_month}")
    if route.notes:
        logger.info(f"  Hinweis:  {route.notes}")
    logger.info("#" * 60)

    if args.dry_run:
        print(f"\n[DRY RUN] Routing: {args.source_env} → {args.target_env}")
        print(f"  Route:    {route.description}")
        print(f"  Workflow: {route.workflow}")
        print(f"  Quelle-Env:  {source_env_cfg.env_file}  ({cfg.mstr.base_url})")
        if is_cross_env and cfg.target_mstr:
            print(f"  Ziel-Env:    {target_env_cfg.env_file}  ({cfg.target_mstr.base_url})")
        if backup_month:
            print(f"  Backup-Projekt: {cfg.project.backup_base_name} {backup_month}")
        if route.notes:
            print(f"  Hinweis: {route.notes}")
        if route.workflow == WORKFLOW_BACKUP_DUPLICATE_THEN_VERSORGUNG_MERGE:
            print_dry_run_mit(cfg, backup_month, target_mstr=cfg.target_mstr)
            print("\n  [Schritt 2] Versorgung mit Merge (cross-env) würde danach folgen.")
        elif route.workflow == WORKFLOW_BACKUP_DUPLICATE:
            print_dry_run_mit(cfg, backup_month, target_mstr=cfg.target_mstr)
        elif route.workflow == WORKFLOW_VERSORGUNG_MERGE:
            print_dry_run_mit(cfg, backup_month or "(kein Backup)", target_mstr=cfg.target_mstr)
        else:
            print_dry_run_ohne(cfg)
        return 0

    # ── Workflow ausführen ────────────────────────────────────────────────

    if route.workflow == WORKFLOW_WITHOUT_BACKUP:
        success = workflow_ohne.run(cfg)
        log_run_footer(success)
        return 0 if success else 1

    if route.workflow == WORKFLOW_BACKUP_DUPLICATE:
        success = workflow_mit.run(
            cfg,
            backup_month=backup_month,
            target_mstr=cfg.target_mstr,
        )
        log_run_footer(success)
        return 0 if success else 1

    if route.workflow == WORKFLOW_VERSORGUNG_MERGE:
        # Versorgung cross-env: Methode (duplicate/merge/package) kommt aus BACKUP_METHOD in .env
        success = workflow_mit.run(
            cfg,
            backup_month=backup_month or "",
            target_mstr=cfg.target_mstr,
        )
        log_run_footer(success)
        return 0 if success else 1

    if route.workflow == WORKFLOW_BACKUP_DUPLICATE_THEN_VERSORGUNG_MERGE:
        logger.info("")
        logger.info("═" * 60)
        logger.info("  PHASE 1/2: Backup-Duplizierung (dacg)")
        logger.info("═" * 60)
        success = workflow_mit.run(
            cfg,
            backup_month=backup_month,
            target_mstr=cfg.target_mstr,
        )
        if not success:
            logger.error("  Phase 1 fehlgeschlagen — Phase 2 wird nicht ausgeführt.")
            log_run_footer(success)
            return 1

        logger.info("")
        logger.info("═" * 60)
        logger.info("  PHASE 2/2: Versorgung ggf. mit Merge (cross-env)")
        logger.info("═" * 60)
        success = workflow_mit.run(
            cfg,
            backup_month=backup_month,
            target_mstr=cfg.target_mstr,
        )
        log_run_footer(success)
        return 0 if success else 1

    parser.error(f"Unbekannter Workflow-Typ in Routing-Matrix: '{route.workflow}'")
    return 1  # unreachable


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # --show-routes: Routing-Matrix ausgeben und beenden
    if getattr(args, "show_routes", False):
        print(describe_routing_matrix())
        return 0

    # Acquire lock to prevent concurrent deployments
    if not acquire_lock():
        return 1

    # ── Route-basierter Pfad: --source-env + --target-env ─────────────────
    if getattr(args, "source_env", None) or getattr(args, "target_env", None):
        if not (args.source_env and args.target_env):
            parser.error(
                "--source-env und --target-env müssen immer zusammen angegeben werden."
            )
        try:
            return _run_routing(args, parser)
        finally:
            release_lock()

    try:
        cfg = load_config(env_file=args.env)
        if (
            args.target_base_url or args.target_username or args.target_password
        ):
            missing_target = [
                name
                for name, value in [
                    ("--target-base-url", args.target_base_url),
                    ("--target-username", args.target_username),
                    ("--target-password", args.target_password),
                ]
                if not value
            ]
            if missing_target:
                parser.error(
                    "When using target environment options, all of "
                    "--target-base-url, --target-username and "
                    "--target-password must be provided."
                )

            cfg.target_mstr = MstrConfig(
                base_url=args.target_base_url,
                username=args.target_username,
                password=args.target_password,
                login_mode=args.target_login_mode,
            )

        # Determine workflow and backup month
        create_backup = cfg.create_backup
        backup_month = args.backup_month or cfg.backup_month
        if create_backup and not backup_month:
            parser.error("BACKUP_MONTH must be set in config or provided via --backup-month when CREATE_BACKUP=true")
        if create_backup and cfg.project.backup_method == "package" and cfg.target_mstr is None:
            parser.error(
                "BACKUP_METHOD=package requires a target environment. "
                "Set TARGET_MSTR_BASE_URL, TARGET_MSTR_USERNAME, TARGET_MSTR_PASSWORD "
                "in the config file or provide --target-* options."
            )

        command = "mit-backup" if create_backup else "ohne-backup"

        logger = setup_logger(cfg.log.log_dir, cfg.log.log_file_name, command=command)

        logger.info("")
        logger.info("#" * 60)
        logger.info("  Strategy Deployment Tool")
        logger.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  Workflow: {command}")
        logger.info(f"  Server:   {cfg.mstr.base_url}")
        logger.info(f"  Project:  {cfg.project.project_name}")
        if create_backup:
            logger.info(f"  Backup:   {cfg.project.backup_base_name} {backup_month}")
        logger.info("#" * 60)

        if args.dry_run:
            if create_backup:
                print_dry_run_mit(
                    cfg,
                    backup_month,
                    target_mstr=cfg.target_mstr,
                )
            else:
                print_dry_run_ohne(cfg)
            return 0

        if create_backup:
            success = workflow_mit.run(
                cfg,
                backup_month=backup_month,
                target_mstr=cfg.target_mstr,
            )
        else:
            success = workflow_ohne.run(cfg)

        log_run_footer(success)
        return 0 if success else 1
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())