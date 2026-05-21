"""
workflows/incremental_refresh_report.py – Execute an IncrementalRefreshReport
and reliably detect success.

BACKGROUND
----------
The mstrio-py `IncrementalRefreshReport.execute()` method submits a publish job
and returns a Job object.  The problem: once the job reaches a terminal state,
the server drops it from the active-jobs API — subsequent `.fetch()` calls raise
an error (similar to an ICube refresh job).

This module implements three complementary strategies for success detection,
in order of reliability:

  Strategy A – Exception guard (primary)
    Wrap execute() in try/except.  Any server-side failure (bad credentials,
    project not loaded, modelling service unavailable, …) surfaces as a
    MstrException / IServerError.  If no exception is raised, the job was
    accepted and ran to completion as far as the server is concerned.

  Strategy B – Job status polling (while the job is alive)
    After execute() returns a Job, poll job.status in a short loop.  Once the
    server drops the job (raises), we exit the loop.  The last observed status
    before the drop tells us whether it completed successfully or was aborted.

  Strategy C – Target cube last-modified timestamp (post-execution check)
    Before execution, record the cube's `last_modified` timestamp.
    After execution, re-fetch the cube and compare.  An unchanged timestamp
    means the refresh did not touch the cube — likely a silent failure or a
    no-op.  A newer timestamp confirms data was written.

USAGE
-----
  python incremental_refresh_report.py

Configure via environment variables or directly in the script below.

REQUIREMENTS
------------
  - MicroStrategy Library with Modelling Services enabled (Cloud environment)
  - pip install mstrio-py

REFERENCES
----------
  mstrio-py code snippet:
    https://github.com/MicroStrategy/mstrio-py/blob/master/code_snippets/incremental_refresh_report.py
  mstrio-py IncrementalRefreshReport API docs:
    https://www2.microstrategy.com/producthelp/Current/mstrio-py/
"""

import logging
import os
import time
from datetime import datetime
from typing import Optional

from mstrio.connection import Connection
from mstrio.project_objects.incremental_refresh_report import IncrementalRefreshReport
from mstrio.project_objects.datasets.olap_cube import OlapCube

# ---------------------------------------------------------------------------
# Configuration — override via environment variables or edit directly here
# ---------------------------------------------------------------------------

BASE_URL    = os.getenv("MSTR_BASE_URL",    "https://your-server/MicroStrategyLibrary")
USERNAME    = os.getenv("MSTR_USERNAME",    "Administrator")
PASSWORD    = os.getenv("MSTR_PASSWORD",    "")
LOGIN_MODE  = int(os.getenv("MSTR_LOGIN_MODE", "1"))
PROJECT     = os.getenv("MSTR_PROJECT_NAME", "Your Project")

# ID of the IncrementalRefreshReport to execute
IRR_ID      = os.getenv("IRR_ID", "A2E990E9493E3319526663A8FAD998A5")

# ID of the target OlapCube that the IRR refreshes (used for Strategy C)
# Leave empty to skip the timestamp check.
TARGET_CUBE_ID = os.getenv("E3CE909FA9490EE28D63C080EDB9B2B1", "")

# Polling settings for Strategy B
JOB_POLL_INTERVAL_S = 10   # seconds between status polls
JOB_POLL_MAX_S      = 300  # give up polling after this many seconds

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("irr_test")


# ---------------------------------------------------------------------------
# Strategy C helper – cube timestamp
# ---------------------------------------------------------------------------

def _get_cube_last_modified(conn: Connection, cube_id: str) -> Optional[datetime]:
    """Return the cube's last_modified datetime, or None if unavailable."""
    if not cube_id:
        return None
    try:
        cube = OlapCube(conn, id=cube_id)
        ts = getattr(cube, "last_modified", None)
        if ts is None:
            # Some mstrio versions expose it as modification_time
            ts = getattr(cube, "modification_time", None)
        if isinstance(ts, str):
            # Parse ISO-8601 string if necessary
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return ts
    except Exception as exc:
        logger.warning(f"  [Strategy C] Could not read cube timestamp: {exc}")
        return None


# ---------------------------------------------------------------------------
# Strategy B helper – job polling
# ---------------------------------------------------------------------------

def _poll_job(job, timeout_s: int = JOB_POLL_MAX_S) -> Optional[str]:
    """
    Poll job.status until the job disappears from the server (terminal state)
    or timeout is reached.

    Returns the last successfully observed status string, or None if the job
    was never readable.
    """
    start = time.time()
    last_status = None

    while time.time() - start < timeout_s:
        try:
            job.fetch()
            last_status = str(job.status)
            elapsed = int(time.time() - start)
            logger.info(f"  [Strategy B] Job status [{elapsed:>4}s]: {last_status}")

            # Some mstrio builds expose a terminal status we can check here
            upper = last_status.upper()
            if "COMPLETE" in upper or "SUCCESS" in upper:
                logger.info("  [Strategy B] Job reached terminal SUCCESS state.")
                return last_status
            if "FAILED" in upper or "ERROR" in upper or "CANCEL" in upper:
                logger.warning(f"  [Strategy B] Job reached terminal FAILURE state: {last_status}")
                return last_status

        except Exception as exc:
            # Server dropped the job — this is the expected terminal signal
            logger.info(
                f"  [Strategy B] Job no longer queryable (server dropped it): {exc}\n"
                f"  Last observed status: {last_status}"
            )
            return last_status

        time.sleep(JOB_POLL_INTERVAL_S)

    logger.warning(f"  [Strategy B] Polling timeout after {timeout_s}s. Last status: {last_status}")
    return last_status


# ---------------------------------------------------------------------------
# Main execution function
# ---------------------------------------------------------------------------

def run_irr(
    base_url: str = BASE_URL,
    username: str = USERNAME,
    password: str = PASSWORD,
    login_mode: int = LOGIN_MODE,
    project: str = PROJECT,
    irr_id: str = IRR_ID,
    target_cube_id: str = TARGET_CUBE_ID,
) -> bool:
    """
    Execute the IncrementalRefreshReport and detect success using all three
    strategies.  Returns True if all active strategies agree on success.
    """
    if not irr_id:
        logger.error("IRR_ID is not set. Set the IRR_ID environment variable or edit the script.")
        return False

    logger.info("=" * 60)
    logger.info("  IncrementalRefreshReport – Execution & Success Detection")
    logger.info(f"  Server:  {base_url}")
    logger.info(f"  Project: {project}")
    logger.info(f"  IRR ID:  {irr_id}")
    if target_cube_id:
        logger.info(f"  Cube ID: {target_cube_id} (Strategy C timestamp check)")
    logger.info("=" * 60)

    results: dict[str, Optional[bool]] = {
        "strategy_a_exception": None,
        "strategy_b_job_poll":  None,
        "strategy_c_timestamp": None,
    }

    conn = Connection(
        base_url=base_url,
        username=username,
        password=password,
        login_mode=login_mode,
        project_name=project,
    )

    try:
        irr = IncrementalRefreshReport(conn, id=irr_id)
        logger.info(f"\n  Report name: {getattr(irr, 'name', '(unknown)')}")

        # ── Strategy C: record cube timestamp BEFORE execution ────────────
        ts_before = _get_cube_last_modified(conn, target_cube_id)
        if ts_before:
            logger.info(f"\n  [Strategy C] Cube last_modified BEFORE: {ts_before}")

        # ── Strategy A + B: execute and poll ─────────────────────────────
        logger.info("\n  Executing IncrementalRefreshReport...")
        try:
            job = irr.execute()
            results["strategy_a_exception"] = True
            logger.info(f"  [Strategy A] execute() returned without exception — job accepted.")

            # ── Strategy B: poll while job is alive ───────────────────────
            if job is not None:
                logger.info(f"  [Strategy B] Polling job {getattr(job, 'id', '?')}...")
                last_status = _poll_job(job)
                if last_status is not None:
                    upper = last_status.upper()
                    if "FAILED" in upper or "ERROR" in upper or "CANCEL" in upper:
                        results["strategy_b_job_poll"] = False
                    else:
                        # Job disappeared without a failure status = completed successfully
                        results["strategy_b_job_poll"] = True
                else:
                    logger.warning("  [Strategy B] No job status was ever readable — inconclusive.")
            else:
                logger.info("  [Strategy B] execute() returned None — no job to poll (synchronous execution?).")

        except Exception as exc:
            results["strategy_a_exception"] = False
            logger.error(f"  [Strategy A] execute() raised an exception: {exc}")

        # ── Strategy C: compare cube timestamp AFTER execution ────────────
        if target_cube_id:
            # Give the server a moment to flush the cube metadata
            time.sleep(5)
            ts_after = _get_cube_last_modified(conn, target_cube_id)
            if ts_after:
                logger.info(f"  [Strategy C] Cube last_modified AFTER:  {ts_after}")
                if ts_before and ts_after > ts_before:
                    logger.info("  [Strategy C] Timestamp advanced — cube was refreshed. ✓")
                    results["strategy_c_timestamp"] = True
                elif ts_before and ts_after == ts_before:
                    logger.warning(
                        "  [Strategy C] Timestamp unchanged — cube was NOT refreshed. "
                        "Possible silent failure or no new data."
                    )
                    results["strategy_c_timestamp"] = False
                else:
                    logger.info("  [Strategy C] No before-timestamp to compare — skipped.")
            else:
                logger.info("  [Strategy C] Could not read post-execution timestamp — skipped.")

    finally:
        conn.close()

    # ── Summary ───────────────────────────────────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("  SUCCESS DETECTION SUMMARY")
    logger.info("=" * 60)
    for strategy, result in results.items():
        if result is None:
            verdict = "N/A  (not applicable / inconclusive)"
        elif result:
            verdict = "✓  SUCCESS"
        else:
            verdict = "✗  FAILURE"
        logger.info(f"  {strategy:<30} {verdict}")

    # Overall: any active (non-None) strategy that reports failure → overall failure
    active = {k: v for k, v in results.items() if v is not None}
    overall = all(active.values()) if active else False
    logger.info("-" * 60)
    logger.info(f"  Overall result: {'SUCCESS' if overall else 'FAILURE or INCONCLUSIVE'}")
    logger.info("=" * 60)
    return overall


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    success = run_irr()
    raise SystemExit(0 if success else 1)
