"""
config.py - Reads deployment.env and makes all settings available to the app.

YOU DO NOT NEED TO EDIT THIS FILE.
All configuration is done in deployment.env.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values


# ── Data classes (internal representation of deployment.env) ─────────────────
# These are filled automatically from deployment.env — do not edit here.

@dataclass
class MstrConfig:
    """Holds the Strategy server connection details (Section 1)."""
    base_url: str
    username: str
    password: str
    login_mode: int = 1


@dataclass
class ProjectConfig:
    """Holds the project, DB connection, and security role settings (Sections 2-5)."""
    project_name: str
    project_id: Optional[str]
    backup_base_name: str
    backup_method: str  # "duplicate" or "merge" (when available)
    db_connection_name: str
    db_catalog_name: str
    # Legacy parity options for duplication behavior.
    duplicate_match_users_by_login: bool = False
    duplicate_use_same_identifier_as_source_project: bool = False
    duplicate_copy_project_related_objects: bool = True
    duplicate_copy_schema_related_objects_only: bool = False
    duplicate_copy_users_mode: str = "copy_no_users"
    duplicate_sync_with_target_environment: bool = True
    # List of (role_name, group_name) tuples built from REVOKE_ROLE_GROUP_PAIRS
    revoke_role_group_pairs: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class LogConfig:
    """Holds the logging settings (Section 6)."""
    log_file_name: str
    log_dir: Path


@dataclass
class AppConfig:
    """Top-level container — passed into every workflow."""
    mstr: MstrConfig
    project: ProjectConfig
    log: LogConfig
    target_mstr: Optional[MstrConfig] = None
    create_backup: bool = False
    backup_month: str = ""
    enable_db_catalog_change: bool = True
    enable_schema_update: bool = False
    enable_security_role_revocation: bool = True
    projects: list[str] = field(default_factory=list)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _require(key: str, value: Optional[str], env_file: str) -> str:
    """Exit early with a clear message if a required key is missing."""
    if not value:
        print(f"[ERROR] Missing required value '{key}' in {env_file}")
        print(f"        Open {env_file} and fill in this value.")
        sys.exit(1)
    return value


def _parse_revoke_pairs(raw: str) -> list[tuple[str, str]]:
    """
    Parse REVOKE_ROLE_GROUP_PAIRS from deployment.env into a list of tuples.

    Input:  "Normale Benutzer|Everyone,Normale Benutzer|SGB II Projektzugriff"
    Output: [("Normale Benutzer", "Everyone"), ("Normale Benutzer", "SGB II Projektzugriff")]
    """
    pairs = []
    if not raw:
        return pairs
    for entry in raw.split(","):
        entry = entry.strip()
        if "|" not in entry:
            continue  # skip malformed entries
        role, group = entry.split("|", 1)
        pairs.append((role.strip(), group.strip()))
    return pairs


def _parse_bool(raw: Optional[str], default: bool) -> bool:
    """Parse common truthy/falsy env values with a fallback default."""
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _parse_list(raw: Optional[str]) -> list[str]:
    """Parse a comma-separated list and remove empty entries."""
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _parse_project_groups(raw: Optional[str]) -> dict[str, list[str]]:
    """
    Parse PROJECT_GROUPS from deployment.env.

    Format:
      Group A=Project 1|Project 2;Group B=Project 3
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
    Expand @GroupName tokens and deduplicate while preserving order.
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


# ── Public loader ─────────────────────────────────────────────────────────────

def load_config(env_file: str = "deployment.env") -> AppConfig:
    """
    Read the given deployment.env file and return a fully validated AppConfig.

    Called automatically by main.py — you do not need to call this yourself.

    Args:
        env_file: Path to the credentials file.
                  If a relative path is given, it is resolved relative to the
                  directory where config.py lives (i.e. the project folder),
                  not wherever Python was launched from.
    """
    # Resolve relative paths against the project folder, not the shell cwd
    path = Path(env_file)
    if not path.is_absolute():
        path = Path(__file__).parent / env_file
    if not path.exists():
        print(f"[ERROR] Configuration file not found: {path.absolute()}")
        print(f"        Make sure '{env_file}' exists in the same folder as main.py")
        sys.exit(1)

    # Read the file into a plain dict WITHOUT touching os.environ.
    # This means multiple configs can be loaded in the same process without
    # values from one file leaking into another.
    v = dotenv_values(str(path))

    # ── Section 1: Server connection ──────────────────────────────────
    mstr = MstrConfig(
        base_url=_require("MSTR_BASE_URL", v.get("MSTR_BASE_URL"), env_file),
        username=_require("MSTR_USERNAME", v.get("MSTR_USERNAME"), env_file),
        password=_require("MSTR_PASSWORD", v.get("MSTR_PASSWORD"), env_file),
        login_mode=int(v.get("MSTR_LOGIN_MODE", "1")),
    )

    target_base_url = v.get("TARGET_MSTR_BASE_URL", "")
    target_username = v.get("TARGET_MSTR_USERNAME", "")
    target_password = v.get("TARGET_MSTR_PASSWORD", "")
    target_login_mode = int(v.get("TARGET_MSTR_LOGIN_MODE", "1"))
    target_mstr = None
    if target_base_url or target_username or target_password:
        if not (target_base_url and target_username and target_password):
            print(f"[ERROR] TARGET_MSTR_BASE_URL, TARGET_MSTR_USERNAME, and TARGET_MSTR_PASSWORD must all be set together in {env_file}")
            sys.exit(1)
        target_mstr = MstrConfig(
            base_url=target_base_url,
            username=target_username,
            password=target_password,
            login_mode=target_login_mode,
        )

    # ── Sections 2-5: Project, backup, DB connection, security roles ──
    project_name = _require("MSTR_PROJECT_NAME", v.get("MSTR_PROJECT_NAME"), env_file)
    project_groups = _parse_project_groups(v.get("PROJECT_GROUPS"))
    projects = _expand_project_tokens(
        _parse_list(v.get("PROJECTS")),
        project_groups,
        env_file,
        "PROJECTS",
    )
    if not projects:
        projects = [project_name]

    project = ProjectConfig(
        project_name=project_name,
        project_id=v.get("MSTR_PROJECT_ID") or None,
        backup_base_name=v.get("BACKUP_PROJECT_BASE_NAME", project_name),
        backup_method=v.get("BACKUP_METHOD", "duplicate").lower(),  # Default to "duplicate"
        db_connection_name=_require("DB_CONNECTION_NAME", v.get("DB_CONNECTION_NAME"), env_file),
        db_catalog_name=_require("DB_CATALOG_NAME", v.get("DB_CATALOG_NAME"), env_file),
        duplicate_match_users_by_login=_parse_bool(v.get("DUPLICATE_MATCH_USERS_BY_LOGIN"), False),
        duplicate_use_same_identifier_as_source_project=_parse_bool(
            v.get("DUPLICATE_USE_SAME_IDENTIFIER_AS_SOURCE_PROJECT"), False
        ),
        duplicate_copy_project_related_objects=_parse_bool(
            v.get("DUPLICATE_COPY_PROJECT_RELATED_OBJECTS"), True
        ),
        duplicate_copy_schema_related_objects_only=_parse_bool(
            v.get("DUPLICATE_COPY_SCHEMA_RELATED_OBJECTS_ONLY"), False
        ),
        duplicate_copy_users_mode=(v.get("DUPLICATE_COPY_USERS_MODE", "copy_no_users") or "copy_no_users").strip().lower(),
        duplicate_sync_with_target_environment=_parse_bool(
            v.get("DUPLICATE_SYNC_WITH_TARGET_ENVIRONMENT"), True
        ),
        revoke_role_group_pairs=_parse_revoke_pairs(v.get("REVOKE_ROLE_GROUP_PAIRS", "")),
    )

    # ── Section 6: Logging ────────────────────────────────────────────
    log = LogConfig(
        log_file_name=v.get("LOG_FILE_NAME", f"LOG_{project_name}.txt"),
        log_dir=Path(v.get("LOG_DIR", ".")),
    )

    return AppConfig(
        mstr=mstr,
        project=project,
        log=log,
        target_mstr=target_mstr,
        create_backup=v.get("CREATE_BACKUP", "false").lower() == "true",
        backup_month=v.get("BACKUP_MONTH", ""),
        enable_db_catalog_change=v.get("ENABLE_DB_CATALOG_CHANGE", "true").lower() == "true",
        enable_schema_update=v.get("ENABLE_SCHEMA_UPDATE", "false").lower() == "true",
        enable_security_role_revocation=v.get("ENABLE_SECURITY_ROLE_REVOCATION", "true").lower() == "true",
        projects=projects,
    )