"""
workflows/cube_last_update_report.py – Read and print the last update timestamp
for a MicroStrategy cube.

USAGE
-----
  python cube_last_update_report.py

REQUIRED ENV VARS
-----------------
  MSTR_BASE_URL
  MSTR_USERNAME
  MSTR_PASSWORD
  MSTR_PROJECT_NAME
  TARGET_CUBE_ID   (or CUBE_ID)

OPTIONAL ENV VARS
-----------------
  MSTR_LOGIN_MODE  (default: 1)
"""

import logging
import os
from datetime import datetime
from typing import Optional

from mstrio.connection import Connection
from mstrio.project_objects.datasets.olap_cube import OlapCube


BASE_URL = os.getenv("MSTR_BASE_URL", "https://your-server/MicroStrategyLibrary")
USERNAME = os.getenv("MSTR_USERNAME", "Administrator")
PASSWORD = os.getenv("MSTR_PASSWORD", "")
LOGIN_MODE = int(os.getenv("MSTR_LOGIN_MODE", "1"))
PROJECT = os.getenv("MSTR_PROJECT_NAME", "Your Project")
TARGET_CUBE_ID = os.getenv("TARGET_CUBE_ID", os.getenv("CUBE_ID", ""))


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cube_last_update")


def get_cube_last_modified(conn: Connection, cube_id: str) -> Optional[datetime]:
    """Return the cube last-modified timestamp, or None if unavailable."""
    if not cube_id:
        return None

    cube = OlapCube(conn, id=cube_id)
    ts = getattr(cube, "last_modified", None)
    if ts is None:
        ts = getattr(cube, "modification_time", None)

    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))

    return ts


def run() -> bool:
    if not TARGET_CUBE_ID:
        logger.error("TARGET_CUBE_ID is not set. Set TARGET_CUBE_ID (or CUBE_ID).")
        return False

    logger.info("=" * 60)
    logger.info("  Cube Last Update Report")
    logger.info(f"  Server:  {BASE_URL}")
    logger.info(f"  Project: {PROJECT}")
    logger.info(f"  Cube ID: {TARGET_CUBE_ID}")
    logger.info("=" * 60)

    conn = Connection(
        base_url=BASE_URL,
        username=USERNAME,
        password=PASSWORD,
        login_mode=LOGIN_MODE,
        project_name=PROJECT,
    )

    try:
        ts = get_cube_last_modified(conn, TARGET_CUBE_ID)
        if ts is None:
            logger.error("Could not read cube last_modified timestamp.")
            return False

        logger.info(f"Cube last_modified: {ts}")
        return True
    except Exception as exc:
        logger.error(f"Failed to fetch cube last_modified: {exc}")
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    success = run()
    raise SystemExit(0 if success else 1)
