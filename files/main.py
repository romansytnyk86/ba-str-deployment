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
from pathlib import Path
from typing import Optional
from dotenv import dotenv_values

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


def _resolve_support_file(path_str: str) -> Path:
    """Resolve support files relative to the files/ directory."""
    path = Path(path_str)
    if not path.is_absolute():
        path = Path(__file__).parent / path
    return path


def _parse_project_groups(raw: Optional[str]) -> dict[str, list[str]]:
    """Parse PROJECT_GROUPS=Group=env1|env2;Other=env3 from a support env file."""
    groups: dict[str, list[str]] = {}
    if not raw:
        return groups

    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        group_name, members_raw = entry.split("=", 1)
        members = [item.strip() for item in members_raw.split("|") if item.strip()]
        if group_name.strip() and members:
            groups[group_name.strip()] = members

    return groups


def load_project_group(group_name: str, groups_file: str) -> list[str]:
    """
    Resolve a project group into a list of env files.

    The group definition file is a dotenv-style file containing:
      PROJECT_GROUPS=Smoke=deployment_a.env|deployment_b.env;Full=deployment_c.env
    """
    path = _resolve_support_file(groups_file)
    if not path.exists():
        raise ValueError(
            f"Project group file not found: {path}. "
            "Create it or pass --groups-file with an existing file."
        )

    values = dotenv_values(str(path))
    groups = _parse_project_groups(values.get("PROJECT_GROUPS"))
    if not groups:
        raise ValueError(
            f"No PROJECT_GROUPS defined in {path.name}. "
            "Define at least one group before using --project-group."
        )

    if group_name not in groups:
        available = ", ".join(sorted(groups))
        raise ValueError(
            f"Unknown project group '{group_name}' in {path.name}. "
            f"Available groups: {available}"
        )

    base_dir = path.parent
    resolved_files: list[str] = []
    for member in groups[group_name]:
        member_path = Path(member)
        if not member_path.is_absolute():
            member_path = base_dir / member_path
        resolved_files.append(str(member_path))

    return resolved_files


def load_project_group_from_deployment_env(group_name: str, env_file: str) -> list[str]:
    """
    Resolve a project group from a deployment env file.

    In this mode, PROJECT_GROUPS members are project names, e.g.:
      PROJECT_GROUPS=Smoke=SGB II S2S|SGB II MaEnde;Core=Project A|Project B
    """
    path = _resolve_support_file(env_file)
    if not path.exists():
        raise ValueError(f"Deployment env file for groups not found: {path}")

    values = dotenv_values(str(path))
    groups = _parse_project_groups(values.get("PROJECT_GROUPS"))
    if not groups:
        raise ValueError(
            f"No PROJECT_GROUPS defined in {path.name}. "
            "Add PROJECT_GROUPS there or use --groups-file fallback."
        )

    if group_name not in groups:
        available = ", ".join(sorted(groups))
        raise ValueError(
            f"Unknown project group '{group_name}' in {path.name}. "
            f"Available groups: {available}"
        )

    return groups[group_name]


def _resolve_group_selection(
    *,
    group_name: str,
    deployment_env_file: str,
    groups_file: str,
) -> tuple[str, list[str], str]:
    """
    Resolve --project-group with precedence:
      1) deployment env PROJECT_GROUPS (members are project names)
      2) --groups-file PROJECT_GROUPS (members are env files)

    Returns:
      (mode, members, source_label)
      mode: "projects" | "env-files"
    """
    try:
        projects = load_project_group_from_deployment_env(group_name, deployment_env_file)
        return ("projects", projects, Path(_resolve_support_file(deployment_env_file)).name)
    except ValueError as env_exc:
        try:
            env_files = load_project_group(group_name, groups_file)
            return ("env-files", env_files, Path(_resolve_support_file(groups_file)).name)
        except ValueError as file_exc:
            raise ValueError(f"{env_exc}\n{file_exc}")


def describe_project_groups(groups_file: str) -> str:
    """Return a readable summary of available project groups."""
    path = _resolve_support_file(groups_file)
    if not path.exists():
        return f"Fallback group file not found: {path.name}"

    values = dotenv_values(str(path))
    groups = _parse_project_groups(values.get("PROJECT_GROUPS"))
    if not groups:
        return f"No PROJECT_GROUPS defined in {path.name}."

    lines = [f"Project groups from {path.name}:"]
    for name in sorted(groups):
        members = ", ".join(groups[name])
        lines.append(f"  {name}: {members}")
    return "\n".join(lines)


def describe_project_groups_in_deployment_env(env_file: str) -> str:
    """Return a readable summary of project groups defined in a deployment env file."""
    path = _resolve_support_file(env_file)
    if not path.exists():
        raise ValueError(f"Deployment env file not found: {path}")

    values = dotenv_values(str(path))
    groups = _parse_project_groups(values.get("PROJECT_GROUPS"))
    if not groups:
        return f"No PROJECT_GROUPS defined in {path.name}."

    lines = [f"Project groups from {path.name} (project names):"]
    for name in sorted(groups):
        members = ", ".join(groups[name])
        lines.append(f"  {name}: {members}")
    return "\n".join(lines)


def _run_loaded_workflow(
    cfg,
    *,
    parser,
    args,
    logger,
    route=None,
    backup_month: Optional[str] = None,
) -> int:
    """Run the selected workflow for an already loaded config."""
    if route is not None:
        if args.dry_run:
            print(f"\n[DRY RUN] Routing: {args.source_env} → {args.target_env}")
            print(f"  Route:    {route.description}")
            print(f"  Workflow: {route.workflow}")
            print(f"  Quelle-Env:  {cfg._source_env_file_label}  ({cfg.mstr.base_url})")
            if cfg.target_mstr:
                print(f"  Ziel-Env:    {cfg._target_env_file_label}  ({cfg.target_mstr.base_url})")
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
        return 1

    create_backup = cfg.create_backup
    resolved_backup_month = backup_month or cfg.backup_month
    if create_backup and not resolved_backup_month:
        parser.error("BACKUP_MONTH must be set in config or provided via --backup-month when CREATE_BACKUP=true")
    if create_backup and cfg.project.backup_method == "package" and cfg.target_mstr is None:
        parser.error(
            "BACKUP_METHOD=package requires a target environment. "
            "Set TARGET_MSTR_BASE_URL, TARGET_MSTR_USERNAME, TARGET_MSTR_PASSWORD "
            "in the config file or provide --target-* options."
        )

    if args.dry_run:
        if create_backup:
            print_dry_run_mit(
                cfg,
                resolved_backup_month,
                target_mstr=cfg.target_mstr,
            )
        else:
            print_dry_run_ohne(cfg)
        return 0

    if create_backup:
        success = workflow_mit.run(
            cfg,
            backup_month=resolved_backup_month,
            target_mstr=cfg.target_mstr,
        )
    else:
        success = workflow_ohne.run(cfg)

    log_run_footer(success)
    return 0 if success else 1


def _run_project_group(args, parser) -> int:
    """Run the selected workflow for PROJECTS or a selected project group."""
    failures: list[tuple[str, int]] = []

    route = None
    source_env_cfg = None
    target_env_cfg = None
    backup_month = args.backup_month
    if args.source_env or args.target_env:
        if not (args.source_env and args.target_env):
            parser.error("--source-env und --target-env müssen immer zusammen angegeben werden.")
        try:
            route = get_route(args.source_env, args.target_env)
            source_env_cfg = get_env_config(args.source_env)
            target_env_cfg = get_env_config(args.target_env)
        except ValueError as exc:
            parser.error(str(exc))
        if route.backup_month_required and not backup_month:
            parser.error(
                f"Route '{args.source_env} → {args.target_env}' erfordert --backup-month "
                f"(z. B. --backup-month 202604)."
            )

    deployment_env_for_groups = source_env_cfg.env_file if source_env_cfg else args.env
    # For routing, allow group definitions to come from the default env file
    # when the route-specific env file (e.g. deployment_design.env) is not present yet.
    if source_env_cfg:
        route_group_env_path = _resolve_support_file(source_env_cfg.env_file)
        if not route_group_env_path.exists():
            deployment_env_for_groups = args.env
    if args.project_group:
        try:
            group_mode, members, group_source = _resolve_group_selection(
                group_name=args.project_group,
                deployment_env_file=deployment_env_for_groups,
                groups_file=args.groups_file,
            )
        except ValueError as exc:
            parser.error(str(exc))
        selection_label = args.project_group
    else:
        cfg_for_projects = load_config(env_file=deployment_env_for_groups)
        members = cfg_for_projects.projects
        group_mode = "projects"
        group_source = f"{Path(_resolve_support_file(deployment_env_for_groups)).name}:PROJECTS"
        selection_label = "PROJECTS"

    total = len(members)

    shared_target_cfg = None
    if route is not None and args.source_env.lower() != args.target_env.lower():
        shared_target_cfg = load_config(env_file=target_env_cfg.env_file)

    print(f"\n[PROJECT GROUP] {selection_label} ({total} members) from {group_source}")
    for index, member in enumerate(members, 1):
        if group_mode == "projects":
            cfg = load_config(env_file=deployment_env_for_groups)
            cfg.project.project_name = member
            cfg.project.project_id = None
            cfg.project.backup_base_name = member
            run_label = member
            env_label = Path(_resolve_support_file(deployment_env_for_groups)).name
        else:
            cfg = load_config(env_file=member)
            run_label = cfg.project.project_name
            env_label = Path(member).name

        print(f"\n[{index}/{total}] {run_label}")

        if route is not None:
            if shared_target_cfg is not None:
                cfg.target_mstr = shared_target_cfg.mstr
            elif args.source_env.lower() == args.target_env.lower():
                cfg.target_mstr = None

            if backup_month:
                cfg.backup_month = backup_month

            logger = setup_logger(
                cfg.log.log_dir,
                cfg.log.log_file_name,
                command=f"{args.source_env}→{args.target_env}:{cfg.project.project_name}",
            )
            cfg._source_env_file_label = env_label
            cfg._target_env_file_label = target_env_cfg.env_file

            logger.info("")
            logger.info("#" * 60)
            logger.info("  Strategy Deployment Tool  [Umgebungsrouting + Projektgruppe]")
            logger.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"  Gruppe:   {selection_label}")
            logger.info(f"  Projekt:  {cfg.project.project_name}")
            logger.info(f"  Quelle:   {args.source_env}  ({source_env_cfg.description})")
            logger.info(f"  Ziel:     {args.target_env}  ({target_env_cfg.description})")
            logger.info(f"  Quelle-Env-Datei: {env_label}")
            logger.info(f"  Gruppenquelle: {group_source}")
            logger.info(f"  Route:    {route.description}")
            logger.info(f"  Workflow: {route.workflow}")
            logger.info(f"  Server:   {cfg.mstr.base_url}")
            if cfg.target_mstr:
                logger.info(f"  Ziel-Srv: {cfg.target_mstr.base_url}")
            if backup_month:
                logger.info(f"  Backup:   {cfg.project.backup_base_name} {backup_month}")
            if route.notes:
                logger.info(f"  Hinweis:  {route.notes}")
            logger.info("#" * 60)

            exit_code = _run_loaded_workflow(
                cfg,
                parser=parser,
                args=args,
                logger=logger,
                route=route,
                backup_month=backup_month,
            )
        else:
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

            logger = setup_logger(
                cfg.log.log_dir,
                cfg.log.log_file_name,
                command=f"project-group:{selection_label}:{cfg.project.project_name}",
            )
            logger.info("")
            logger.info("#" * 60)
            logger.info("  Strategy Deployment Tool  [Projektgruppe]")
            logger.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"  Gruppe:   {selection_label}")
            logger.info(f"  Gruppenquelle: {group_source}")
            logger.info(f"  Projekt:  {cfg.project.project_name}")
            logger.info(f"  Env-Datei:{env_label}")
            logger.info(f"  Server:   {cfg.mstr.base_url}")
            logger.info("#" * 60)

            exit_code = _run_loaded_workflow(
                cfg,
                parser=parser,
                args=args,
                logger=logger,
                backup_month=backup_month,
            )

        if exit_code != 0:
            failures.append((run_label, exit_code))
            break

    if failures:
        print(f"\n[PROJECT GROUP] Stopped after failure in {failures[0][0]}.")
        return 1

    print(f"\n[PROJECT GROUP] Completed {total} project(s) successfully.")
    return 0


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
        "--project-group",
        metavar="NAME",
        help=(
            "Run the selected workflow for all members in the named group. "
            "The CLI first reads PROJECT_GROUPS from deployment env, then falls back to --groups-file."
        ),
    )
    parser.add_argument(
        "--groups-file",
        metavar="FILE",
        default="project_groups.env",
        help="Fallback project group definition file (default: project_groups.env)",
    )
    parser.add_argument(
        "--show-project-groups",
        action="store_true",
        help="Show available project groups from --groups-file and exit.",
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

    if args.project_group:
        return _run_project_group(args, parser)

    # Quell-Konfiguration laden
    cfg = load_config(env_file=source_env_cfg.env_file)

    # Wartungsfenster-like behavior for routing: if PROJECTS contains
    # multiple entries, run the route workflow for all listed projects.
    if len(cfg.projects) > 1:
        return _run_project_group(args, parser)

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

    cfg._source_env_file_label = source_env_cfg.env_file
    cfg._target_env_file_label = target_env_cfg.env_file
    return _run_loaded_workflow(
        cfg,
        parser=parser,
        args=args,
        logger=logger,
        route=route,
        backup_month=backup_month,
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, "show_project_groups", False):
        try:
            group_env_file = args.env
            if getattr(args, "source_env", None):
                source_env_cfg = get_env_config(args.source_env)
                route_group_env_path = _resolve_support_file(source_env_cfg.env_file)
                group_env_file = source_env_cfg.env_file if route_group_env_path.exists() else args.env
            print(describe_project_groups_in_deployment_env(group_env_file))
            cfg_show = load_config(env_file=group_env_file)
            print("")
            print(f"PROJECTS from {Path(_resolve_support_file(group_env_file)).name}: {', '.join(cfg_show.projects)}")
            print("")
            print(describe_project_groups(args.groups_file))
            return 0
        except ValueError as exc:
            parser.error(str(exc))

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

    if getattr(args, "project_group", None):
        try:
            return _run_project_group(args, parser)
        finally:
            release_lock()

    try:
        cfg = load_config(env_file=args.env)

        # Wartungsfenster-like behavior: if PROJECTS contains multiple entries,
        # run the workflow for all listed projects even without --project-group.
        if len(cfg.projects) > 1:
            return _run_project_group(args, parser)

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

        command = "mit-backup" if cfg.create_backup else "ohne-backup"

        logger = setup_logger(cfg.log.log_dir, cfg.log.log_file_name, command=command)

        logger.info("")
        logger.info("#" * 60)
        logger.info("  Strategy Deployment Tool")
        logger.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  Workflow: {command}")
        logger.info(f"  Server:   {cfg.mstr.base_url}")
        logger.info(f"  Project:  {cfg.project.project_name}")
        if cfg.create_backup:
            logger.info(f"  Backup:   {cfg.project.backup_base_name} {args.backup_month or cfg.backup_month}")
        logger.info("#" * 60)
        return _run_loaded_workflow(
            cfg,
            parser=parser,
            args=args,
            logger=logger,
            backup_month=args.backup_month or cfg.backup_month,
        )
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())