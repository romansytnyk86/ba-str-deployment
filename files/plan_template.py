"""Universal release plan template for MicroStrategy deployments.

Copy this file and customize for each release. Export a PLAN dict containing:
  - change_id, description
  - source_project_source, target_project_source
  - projects, project_batches
  - start_phase_1, start_phase_2, eval_phase, end_phase configurations

All sections have defaults and examples below.
"""

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
    "projects": [
        # List all projects managed in this release 
        "Project A",
        "Project B",
        "Project C",
    ],

    "project_batches": [
        # Define load/unload order and grouping (batch pauses applied between)
        ["Project A", "Project B"],
        ["Project C"],
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
