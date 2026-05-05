"""Universal release plan template for MicroStrategy deployments.

Copy this file and customize for each release. Export a PLAN dict containing:
  - change_id, description
  - source_project_source, target_project_source
  - projects, project_batches
  - start_phase_1, start_phase_2, eval_phase, end_phase configurations

All sections have defaults and examples below.

PROJECT GROUPS
--------------
Use PROJECT_GROUPS to define reusable sets of projects and reference them via
get_project_group() anywhere a project list is expected.

Example:
    PROJECT_GROUPS = {
        "SGB II":      ["SGB II S2S", "SGB II S2S ZD", "SGB II S2S Relational", "SGB II S2S ZD CON"],
        "SGB III":     ["SGB III BioData 2026", "SGB III GPZ 2026"],
        "SGB III kal": ["SGB III BioData 2026", "SGB III Bio LBB"],
    }

    "projects": get_project_group("SGB II") + get_project_group("SGB III"),

If the name is not in PROJECT_GROUPS it is returned as a single-item list so you
can also use it for individual projects without a special case:
    "projects": get_project_group("SGB II S2S"),
"""

# ---------------------------------------------------------------------------
# Define reusable project groups here.
# Group names are arbitrary — choose names that match your release scope.
# ---------------------------------------------------------------------------
PROJECT_GROUPS: dict[str, list[str]] = {
    "SGB II": ["SGB II S2S", "SGB II S2S ZD", "SGB II S2S Relational", "SGB II S2S ZD CON"],
    "SGB III": ["SGB III BioData 2026", "SGB III GPZ 2026"],
    "SGB III kal": ["SGB III BioData 2026", "SGB III Bio LBB"],
}


def get_project_group(name: str) -> list[str]:
    """Return the project list for a named group, or [name] for individual projects."""
    if name in PROJECT_GROUPS:
        return PROJECT_GROUPS[name]
    # Treat as a single project name so callers are consistent
    return [part.strip() for part in name.split(",") if part.strip()]


PLAN: dict = {
    # =========================================================================
    # CHANGE METADATA
    # =========================================================================
    "change_id": "CHG000000000",
    "description": "Template release - customize for your deployment",
    
    # Source and target MicroStrategy server node identifiers (for logging/reference)
    "source_project_source": "017311 - BICO-Integration-IS",
    "target_project_source": "017511 - BICO-Bereitstellung-IS-K1",

    # =========================================================================
    # PROJECTS AND BATCHING
    # =========================================================================
    # List all projects managed in this release.
    # Use get_project_group("Group Name") to expand a named group, or list
    # project names directly. You can combine both:
    #   get_project_group("SGB II") + get_project_group("SGB III")
    "projects": (
        get_project_group("Project A") +
        get_project_group("Project B") +
        get_project_group("Project C")
    ),

    "project_batches": [
        # Define load/unload order and grouping (batch pauses applied between).
        # Use get_project_group() here too to keep batch definitions DRY.
        get_project_group("Project A") + get_project_group("Project B"),
        get_project_group("Project C"),
    ],

    # =========================================================================
    # PHASE: start-1 (Maintenance window start)
    # Revoke access → disconnect users → delete caches → unload projects
    # =========================================================================
    "start_phase_1": {
        "batch_pause_seconds": 25,

        "revoke_pairs": [
            # Security role pairs to revoke before unloading
            {"role": "Normale Benutzer", "group": "User Group A", "project": "Project A"},
            {"role": "Normale Benutzer", "group": "User Group B", "project": "Project A"},
            # Add all role/group/project combinations that need to be revoked
        ],

        "cache_cleanup_projects": [
            # Projects whose caches are deleted before unloading
            # "Project A",
        ],
    },

    # =========================================================================
    # PHASE: start-2 (Deployment content)
    # Load → alter DB catalogs → reload → merge → schema update → cache → log
    # =========================================================================
    "start_phase_2": {
        "batch_pause_seconds": 25,
        "pause_after_catalog_update_seconds": 25,

        "db_catalog_updates": [
            # DB connection catalog changes for the new reporting period
            # Example: BM202502 → BM202602
            # {
            #     "connection_name": "Project X - Connection Name - MSAS@SERVER",
            #     "catalog": "con_projectx_202602",
            # },
        ],

        "merges": [
            # Project migrations from source to target
            # Set "enabled": False to skip a merge without removing it
            # {
            #     "source_project": "Project A",
            #     "target_project": "Project A",
            #     "enabled": True,
            # },
        ],

        "schema_update_projects": [
            # Projects requiring schema refresh after reload
            # "Project A",
            # "Project B",
        ],

        "cache_cleanup_projects": [
            # Projects whose caches are deleted after schema update
            # "Project A",
        ],

        "list_db_connections": [
            # DB connections to log (LIST PROPERTIES FOR DBCONNECTION)
            # "Project X - Connection Name - MSAS@SERVER",
        ],

        "list_project_configurations": [
            # Projects to log (LIST PROPERTIES FOR PROJECT CONFIGURATION)
            # "Project A",
            # "Project B",
        ],

        "list_server_configuration": True,
    },

    # =========================================================================
    # PHASE: eval (Evaluation access)
    # Grant evaluation access to evaluation user groups
    # =========================================================================
    "eval_phase": {
        "access_pairs": [
            # Security role pairs to grant for evaluation
            # {
            #     "role": "Normale Benutzer",
            #     "group": "Evaluation Group A",
            #     "project": "Project A",
            # },
        ],
    },

    # =========================================================================
    # PHASE: end (Maintenance window end)
    # Load → delete caches → grant all access
    # =========================================================================
    "end_phase": {
        "load_projects": [
            # Projects to load at the end (usually all projects)
            "Project A",
            "Project B",
            "Project C",
        ],

        "pause_after_load_seconds": 20,

        "cache_cleanup_projects": [
            # Projects whose caches are deleted after final load
            # "Project A",
        ],

        "pause_after_grant_seconds": 10,

        "access_pairs": [
            # All security role pairs to grant (eval + standard groups)
            # {
            #     "role": "Normale Benutzer",
            #     "group": "User Group A",
            #     "project": "Project A",
            # },
        ],
    },
}
