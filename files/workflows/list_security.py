"""
workflows/list_security.py - Helper command to list security roles and groups.

Used to find exact role/group names when preflight reports not found errors.
"""

import logging
from typing import Optional

from config import AppConfig
from mstr.connection import mstr_connection
from utils.process_report import ProcessReport

logger = logging.getLogger("sgb2_freigabe")


def _should_run_step(step_id: int, only_steps: set[int], skip_steps: set[int]) -> bool:
    if only_steps and step_id not in only_steps:
        return False
    if step_id in skip_steps:
        return False
    return True


def _print_matches(title: str, names: list[str], needles: list[str], limit: int = 30) -> None:
    logger.info("")
    logger.info(title)
    if not names:
        logger.info("  [WARN] No items returned")
        return

    lower_needles = [n.lower() for n in needles if n]
    if lower_needles:
        names = [n for n in names if any(needle in n.lower() for needle in lower_needles)]

    if not names:
        logger.info("  [WARN] No items matched the filter terms")
        return

    for idx, name in enumerate(sorted(names)[:limit], start=1):
        logger.info(f"  {idx:>2}. {name}")

    if len(names) > limit:
        logger.info(f"  ... and {len(names) - limit} more")


def run(
    cfg: AppConfig,
    only_steps: Optional[set[int]] = None,
    skip_steps: Optional[set[int]] = None,
    report: Optional[ProcessReport] = None,
) -> bool:
    """List available security roles and user groups in target environment."""
    errors: list[str] = []
    only_steps = only_steps or set()
    skip_steps = skip_steps or set()

    if _should_run_step(1, only_steps, skip_steps):
        if report:
            report.start_step(1, "list_security_objects")

        logger.info("[Helper 1/1] List security roles and groups on target")

        try:
            with mstr_connection(cfg.mstr) as conn:
                roles_resp = conn.get(endpoint="/api/securityRoles")
                groups_resp = conn.get(endpoint="/api/usergroups")

                role_names = [x.get("name", "") for x in roles_resp.json() if x.get("name")]
                group_names = [x.get("name", "") for x in groups_resp.json() if x.get("name")]

                # Show likely matches first so operators can quickly update deployment.env.
                _print_matches(
                    title="Roles containing 'user', 'normal', or 'sgb':",
                    names=role_names,
                    needles=["user", "normal", "sgb"],
                )
                _print_matches(
                    title="Groups containing 'sgb' or 'projekt':",
                    names=group_names,
                    needles=["sgb", "projekt"],
                )

                logger.info("")
                logger.info(f"Total roles returned:  {len(role_names)}")
                logger.info(f"Total groups returned: {len(group_names)}")

        except Exception as exc:
            logger.error(f"  [ERROR] Could not list security objects: {exc}")
            errors.append("list_security_objects")

        if report:
            report.finish_step(1, success=("list_security_objects" not in errors))
        if errors and cfg.fail_fast:
            logger.error("[FAIL-FAST] Aborting after helper step failure.")
            return False
    else:
        if report:
            report.skip_step(1, "list_security_objects", "filtered by --only/--skip")

    if errors:
        logger.error(f"[FAILED] list-security finished with {len(errors)} error(s): {', '.join(errors)}")
        return False

    logger.info("[SUCCESS] list-security completed successfully")
    return True
