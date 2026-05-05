"""
config.py - Reads deployment.env and makes all settings available to the app.

YOU DO NOT NEED TO EDIT THIS FILE.
All configuration is done in deployment.env.
"""

import sys
from getpass import getpass
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class MstrConfig:
    """MicroStrategy server connection details."""
    base_url: str
    username: str
    password: str
    login_mode: int = 1


@dataclass
class LogConfig:
    """Logging settings."""
    log_file_name: str
    log_dir: Path


@dataclass
class AppConfig:
    """Top-level container passed into every workflow."""
    # Target environment (Freigabe)
    mstr: MstrConfig
    # Source environment (Integration) — used for ProjectMerge
    source_mstr: MstrConfig
    log: LogConfig
    # All 6 SGB II projects in the maintenance window
    projects: list[str]
    # Projects for which caches are cleared (e.g. ["SGB II S2S Relational"])
    cache_clear_projects: list[str]
    # Security role / group for revoke+grant
    security_role: str
    security_group: str
    # DB catalog changes: list of (connection_name, new_catalog)
    db_catalog_changes: list[tuple[str, str]]
    # DB connections to list properties for (informational)
    db_connections_to_list: list[str]
    # Projects to merge Integration → Freigabe
    merge_projects: list[str]
    merge_name_prefix: str
    # Batch delays (seconds)
    unload_batch1_delay: int
    unload_batch2_delay: int
    unload_batch3_delay: int
    db_change_delay: int
    load_batch_delay: int
    # Stop immediately on first step failure
    fail_fast: bool = False


# ── Internal helpers ──────────────────────────────────────────────────────────

def _require(key: str, value: Optional[str], env_file: str) -> str:
    if not value:
        print(f"[ERROR] Missing required value '{key}' in {env_file}")
        print(f"        Open {env_file} and fill in this value.")
        sys.exit(1)
    return value


def _resolve_password(key: str, value: Optional[str], env_file: str, prompt_label: str) -> str:
    """
    Use password from env when provided; otherwise prompt securely.
    """
    if value:
        return value
    try:
        pwd = getpass(f"Enter password for {prompt_label} ({key}): ")
    except (EOFError, KeyboardInterrupt):
        print(f"\n[ERROR] Password input aborted for '{key}'.")
        sys.exit(1)
    if not pwd:
        print(f"[ERROR] Missing required value '{key}' in {env_file}")
        print("        Provide it in deployment.env or enter it when prompted.")
        sys.exit(1)
    return pwd


def _parse_bool(raw: Optional[str], default: bool) -> bool:
    if raw is None:
        return default
    v = raw.strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


def _parse_int(raw: Optional[str], default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _parse_list(raw: Optional[str]) -> list[str]:
    """Parse a comma-separated string into a stripped list, ignoring empty entries."""
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _parse_project_groups(raw: Optional[str]) -> dict[str, list[str]]:
    """
    Parse PROJECT_GROUPS from deployment.env.

    Format:
      "Group A=Project 1|Project 2;Group B=Project 3"
    """
    groups: dict[str, list[str]] = {}
    if not raw:
        return groups

    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            continue

        group_name, members_raw = entry.split("=", 1)
        name = group_name.strip()
        members = [p.strip() for p in members_raw.split("|") if p.strip()]
        if name and members:
            groups[name] = members

    return groups


def _expand_project_tokens(
    items: list[str],
    groups: dict[str, list[str]],
    env_file: str,
    field_name: str,
) -> list[str]:
    """
    Expand @GroupName tokens to concrete project names and deduplicate preserving order.
    """
    expanded: list[str] = []
    seen: set[str] = set()

    for item in items:
        if item.startswith("@"):
            group_name = item[1:].strip()
            group_projects = groups.get(group_name)
            if group_projects is None:
                print(
                    f"[ERROR] Unknown project group '{group_name}' used in {field_name} "
                    f"in {env_file}. Define it in PROJECT_GROUPS."
                )
                sys.exit(1)
            for project_name in group_projects:
                if project_name not in seen:
                    expanded.append(project_name)
                    seen.add(project_name)
        else:
            if item not in seen:
                expanded.append(item)
                seen.add(item)

    return expanded


def _parse_catalog_changes(raw: Optional[str]) -> list[tuple[str, str]]:
    """
    Parse DB_CATALOG_CHANGES from deployment.env.
    Input:  "conn_name1|catalog1,conn_name2|catalog2"
    Output: [("conn_name1", "catalog1"), ("conn_name2", "catalog2")]
    """
    pairs: list[tuple[str, str]] = []
    if not raw:
        return pairs
    for entry in raw.split(","):
        entry = entry.strip()
        if "|" not in entry:
            continue
        name, catalog = entry.split("|", 1)
        pairs.append((name.strip(), catalog.strip()))
    return pairs


# ── Public loader ─────────────────────────────────────────────────────────────

def load_config(env_file: str = "deployment.env") -> AppConfig:
    """
    Read the given deployment.env file and return a fully validated AppConfig.
    Called automatically by main.py — you do not need to call this yourself.
    """
    env = dotenv_values(env_file)

    # ── Target (Freigabe) ──
    base_url  = _require("MSTR_BASE_URL",  env.get("MSTR_BASE_URL"),  env_file)
    username  = _require("MSTR_USERNAME",  env.get("MSTR_USERNAME"),  env_file)
    password  = _resolve_password(
        "MSTR_PASSWORD",
        env.get("MSTR_PASSWORD"),
        env_file,
        "target environment",
    )
    login_mode = _parse_int(env.get("MSTR_LOGIN_MODE"), default=1)

    mstr_cfg = MstrConfig(
        base_url=base_url,
        username=username,
        password=password,
        login_mode=login_mode,
    )

    # ── Source (Integration) ──
    src_base_url  = _require("SOURCE_MSTR_BASE_URL",  env.get("SOURCE_MSTR_BASE_URL"),  env_file)
    src_username  = _require("SOURCE_MSTR_USERNAME",  env.get("SOURCE_MSTR_USERNAME"),  env_file)
    src_password  = _resolve_password(
        "SOURCE_MSTR_PASSWORD",
        env.get("SOURCE_MSTR_PASSWORD"),
        env_file,
        "source environment",
    )
    src_login_mode = _parse_int(env.get("SOURCE_MSTR_LOGIN_MODE"), default=1)

    source_mstr_cfg = MstrConfig(
        base_url=src_base_url,
        username=src_username,
        password=src_password,
        login_mode=src_login_mode,
    )

    # ── Projects ──
    project_groups = _parse_project_groups(env.get("PROJECT_GROUPS"))
    projects = _expand_project_tokens(
        _parse_list(env.get("PROJECTS")),
        project_groups,
        env_file,
        "PROJECTS",
    )
    if not projects:
        print(f"[ERROR] PROJECTS must contain at least one project name in {env_file}")
        sys.exit(1)

    # ── Security ──
    security_role  = _require("SECURITY_ROLE",  env.get("SECURITY_ROLE"),  env_file)
    security_group = _require("SECURITY_GROUP", env.get("SECURITY_GROUP"), env_file)

    # ── DB changes ──
    db_catalog_changes   = _parse_catalog_changes(env.get("DB_CATALOG_CHANGES"))
    db_connections_to_list = _parse_list(env.get("DB_CONNECTIONS_TO_LIST"))

    # ── Merge ──
    merge_projects    = _expand_project_tokens(
        _parse_list(env.get("MERGE_PROJECTS")),
        project_groups,
        env_file,
        "MERGE_PROJECTS",
    )
    merge_name_prefix = env.get("MERGE_NAME_PREFIX", "SGB II Freigabe Integration2Freigabe")

    # ── Delays ──
    unload_batch1_delay = _parse_int(env.get("UNLOAD_BATCH1_DELAY"), 20)
    unload_batch2_delay = _parse_int(env.get("UNLOAD_BATCH2_DELAY"), 20)
    unload_batch3_delay = _parse_int(env.get("UNLOAD_BATCH3_DELAY"), 15)
    db_change_delay     = _parse_int(env.get("DB_CHANGE_DELAY"), 25)
    load_batch_delay    = _parse_int(env.get("LOAD_BATCH_DELAY"), 20)

    # ── Logging ──
    log_file_name = env.get("LOG_FILE_NAME", "freigabe_deployment.log")
    log_dir       = Path(env.get("LOG_DIR", "logs"))

    return AppConfig(
        mstr=mstr_cfg,
        source_mstr=source_mstr_cfg,
        log=LogConfig(log_file_name=log_file_name, log_dir=log_dir),
        projects=projects,
        cache_clear_projects=_expand_project_tokens(
            _parse_list(env.get("CACHE_CLEAR_PROJECTS")),
            project_groups,
            env_file,
            "CACHE_CLEAR_PROJECTS",
        ),
        security_role=security_role,
        security_group=security_group,
        db_catalog_changes=db_catalog_changes,
        db_connections_to_list=db_connections_to_list,
        merge_projects=merge_projects,
        merge_name_prefix=merge_name_prefix,
        unload_batch1_delay=unload_batch1_delay,
        unload_batch2_delay=unload_batch2_delay,
        unload_batch3_delay=unload_batch3_delay,
        db_change_delay=db_change_delay,
        load_batch_delay=load_batch_delay,
        fail_fast=_parse_bool(env.get("FAIL_FAST"), default=False),
    )
