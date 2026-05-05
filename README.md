# freigabe_skripte — SGB II Freigabe Maintenance Window (Python)

Pure-Python replacement for the BAT + Command Manager + ProjectMerge.exe
maintenance window workflow defined in **CHG000025131**.

Replaces
────────
| Original file                        | Python equivalent           |
|--------------------------------------|-----------------------------|
| BAT_SGBII_Freigabe_Start_Wartungsfenster_01.bat | `main.py start-01` |
| CM_Start_Wartungsfenster_01.scp       | `workflows/start_01.py`     |
| CM_Start_Wartungsfenster_02.scp       | `workflows/start_01.py`     |
| BAT_SGBII_Freigabe_Start_Wartungsfenster_02.bat | `main.py start-02` |
| CM_Start_Wartungsfenster_03–06.scp    | `workflows/start_02.py`     |
| ProjectMerge.exe (PM_SGB II S2S_-_Integration2Freigabe.xml) | `mstr/merge.py` |
| BAT_SGBII_Freigabe_Ende_Wartungsfenster.bat | `main.py ende`     |
| CM_Ende_Wartungsfenster_01.scp        | `workflows/ende.py`         |

---

## Prerequisites

- Python 3.9+
- MicroStrategy Library accessible from this machine
- `Administrator` account on both Integration and Freigabe environments

```bash
pip install -r requirements.txt
```

---

## Configuration

Edit **`files/deployment.env`** before the first run:

| Key | Description |
|-----|-------------|
| `MSTR_BASE_URL` | Base URL of the Freigabe MicroStrategy Library |
| `MSTR_PASSWORD` | Administrator password for Freigabe (optional in file; prompted securely if blank) |
| `SOURCE_MSTR_BASE_URL` | Base URL of the Integration MicroStrategy Library |
| `SOURCE_MSTR_PASSWORD` | Administrator password for Integration (optional in file; prompted securely if blank) |
| `PROJECT_GROUPS` | Optional reusable groups — see [Project Groups](#project-groups) below |
| `PROJECTS` | Main workflow projects; supports direct names and `@GroupName` references |
| `CACHE_CLEAR_PROJECTS` | Projects whose caches are cleared; supports `@GroupName` |
| `MERGE_PROJECTS` | Projects to merge Integration → Freigabe; supports `@GroupName` |
| `DB_CATALOG_CHANGES` | `conn_name\|new_catalog` pairs — update when month suffix changes |

All other values are pre-filled with the values from CHG000025131 and should
only be changed if the environment configuration changes.

---

## Project Groups

Project groups let you define a named set of projects once and reuse the name
in `PROJECTS`, `CACHE_CLEAR_PROJECTS`, and `MERGE_PROJECTS` using `@GroupName`.

### Defining groups

In `deployment.env`, set `PROJECT_GROUPS` using this format:

```
PROJECT_GROUPS=GroupName=Project 1|Project 2|Project 3;Other Group=Project 4|Project 5
```

- Groups are separated by `;`
- Projects within a group are separated by `|`
- Group names can contain spaces

### Using groups

Reference a group anywhere a project list is accepted with `@GroupName`:

```env
PROJECT_GROUPS=SGB II=SGB II S2S|SGB II Falke Rechtsbehelfe|SGB II MaEnde;SGB II ZD=SGB II S2S ZD|SGB II S2S ZD CON

# Use a whole group
PROJECTS=@SGB II,@SGB II ZD,SGB II S2S Relational

# Mix groups and individual project names freely
MERGE_PROJECTS=@SGB II

# Clear caches only for one project inside a group
CACHE_CLEAR_PROJECTS=SGB II S2S Relational
```

- You can mix `@GroupName` tokens and direct project names in the same value.
- Duplicates across groups or direct names are removed automatically (first occurrence wins).
- If an unknown group name is referenced the script exits immediately with a clear error.

### Current default (no groups)

The existing flat list in `deployment.env` continues to work without any changes:

```env
PROJECT_GROUPS=
PROJECTS=SGB II Falke Rechtsbehelfe,SGB II S2S,SGB II S2S Relational,SGB II S2S ZD,SGB II S2S ZD CON,SGB II MaEnde
```

---

## Usage

Run from the `freigabe_skripte/` directory.

### Preflight (recommended before every run)
```bash
python main.py preflight
```
Read-only checks for:
1. Target/source connectivity
2. Project existence
3. Security role/group existence
4. DB connection existence
5. Merge project configuration

### Phase 1 — Before DB backup (replaces BAT_01)
```bash
python main.py start-01
```
1. Revokes `Normale Benutzer` from `SGB II Projektzugriff` in all 6 projects
2. Disconnects all user connections from all 6 projects
3. Deletes report caches, purges all caching, deletes document caches for `SGB II S2S Relational`

**After this step: start the metadata database backup, then run Phase 2.**

### Phase 2 — After DB backup (replaces BAT_02)
```bash
python main.py start-02
```
1. Unloads all 6 projects in 3 batches (with delays matching original CM script)
2. Updates DB connection catalog strings for 6 connections
3. Loads all 6 projects in 3 batches
4. Runs ProjectMerge: `SGB II S2S` from Integration → Freigabe
5. Updates schema for all 6 projects
6. Clears caches for `SGB II S2S Relational` again
7. Logs current DB connection properties (informational)

### Phase 3 — End of maintenance window (replaces BAT_Ende)
```bash
python main.py ende
```
1. Loads all 6 projects (safety — roles cannot be granted to unloaded projects)
2. Grants `Normale Benutzer` to `SGB II Projektzugriff` in all 6 projects

### Selective step execution
Use this when you need partial reruns:

```bash
python main.py start-02 --only 4,5
python main.py start-02 --skip 4
python main.py ende --only 2
```

Step IDs are the numbered steps shown in each command's console output.

---

## File structure

```
freigabe_skripte/
├── main.py                        # CLI entry point
├── requirements.txt
├── README.md
└── files/
    ├── deployment.env             # ← fill in credentials here
    ├── config.py                  # config loader
    ├── main.py                    # orchestration
    ├── mstr/
    │   ├── connection.py          # connection context manager
    │   ├── project.py             # load / unload / disconnect
    │   ├── security.py            # grant / revoke security roles
    │   ├── schema.py              # schema update
    │   ├── dbconnection.py        # ALTER DBCONNECTION catalog
    │   ├── cache.py               # delete report/document/all caches  [NEW]
    │   └── merge.py               # ProjectMerge via mstrio-py Migration API  [NEW]
    ├── utils/
    │   └── logger.py              # dual console+file logging
    └── workflows/
        ├── start_01.py            # Phase 1
        ├── start_02.py            # Phase 2
        └── ende.py                # Phase 3
```

---

## Notes on ProjectMerge

The `mstr/merge.py` module uses
`Migration.create_project_merge_migration()` from mstrio-py (v11.3.10+).
This is the API equivalent of `projectmerge.exe` and applies the same rules
defined in the original XML file:

- **Application objects** → Replace
- **Configuration objects** → UseExisting
- **Schema objects** → Replace

If your MicroStrategy version does not support this API, the merge step will
fail with a `VersionException`. In that case, run the original
`PM_SGB II S2S_-_Integration2Freigabe.xml` with `projectmerge.exe` manually
and re-enable the remaining steps by running `start-02` with
`MERGE_PROJECTS=` (empty) in `deployment.env`.

---

## Logging

All runs are logged to `files/logs/freigabe_deployment.log` (rotating, 5 MB × 5 files).
The console shows INFO-level messages; the file contains full DEBUG details
and exception tracebacks.

Additionally, each run writes a structured process report JSON file to:

`files/logs/process_reports/`

Each report includes command, step selection (`--only`/`--skip`), per-step status,
duration, and final success flag.
