"""
main.py (root) - CLI launcher for the Freigabe maintenance window tool.

Usage
─────
    python main.py preflight   # Read-only validation before maintenance
    python main.py list-security  # Helper: list available security roles/groups
  python main.py start-01    # Phase 1: Revoke access, disconnect users, clear caches
  python main.py start-02    # Phase 2: Unload, DB update, load, ProjectMerge, schema
  python main.py ende        # Phase 3: Load projects, grant access

Optional step filters:
    --only 1,3                 # run only listed step IDs for the selected command
    --skip 2                   # skip listed step IDs for the selected command

Run from the freigabe_skripte/ root directory.
Configuration is read from files/deployment.env.
"""

import os
import sys
from typing import Optional

# Add files/ to the Python path so config.py, mstr/, utils/, workflows/ are importable
_FILES_DIR = os.path.join(os.path.dirname(__file__), "files")
if _FILES_DIR not in sys.path:
    sys.path.insert(0, _FILES_DIR)

from main import run  # noqa: E402  (import after sys.path modification)


def _parse_step_list(raw: Optional[str]) -> set[int]:
    if not raw:
        return set()
    values: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.add(int(item))
        except ValueError:
            print(f"[ERROR] Invalid step value '{item}'. Use comma-separated integers, e.g. 1,3")
            sys.exit(1)
    return values


def _parse_args(argv: list[str]) -> tuple[str, set[int], set[int]]:
    if len(argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = argv[1].lower()
    only_steps: set[int] = set()
    skip_steps: set[int] = set()

    idx = 2
    while idx < len(argv):
        token = argv[idx]
        if token == "--only":
            if idx + 1 >= len(argv):
                print("[ERROR] Missing value after --only")
                sys.exit(1)
            only_steps = _parse_step_list(argv[idx + 1])
            idx += 2
            continue
        if token == "--skip":
            if idx + 1 >= len(argv):
                print("[ERROR] Missing value after --skip")
                sys.exit(1)
            skip_steps = _parse_step_list(argv[idx + 1])
            idx += 2
            continue
        print(f"[ERROR] Unknown argument '{token}'")
        sys.exit(1)

    return command, only_steps, skip_steps

if __name__ == "__main__":
    command, only_steps, skip_steps = _parse_args(sys.argv)
    env_file = os.path.join(_FILES_DIR, "deployment.env")
    run(
        command=command,
        env_file=env_file,
        only_steps=only_steps,
        skip_steps=skip_steps,
    )
