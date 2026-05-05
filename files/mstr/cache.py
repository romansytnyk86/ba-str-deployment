"""
mstr/cache.py - Cache deletion for MicroStrategy projects.

Replaces these Command Manager commands:
    DELETE REPORT CACHES FROM PROJECT "..."
    PURGE ALL CACHING IN PROJECT "..."
    DELETE DOCUMENT CACHES IN PROJECT "..."

mstrio-py cache API overview
────────────────────────────
mstrio-py exposes content caches (document/dossier caches) via the
ContentCache class in mstrio.project_objects.content_cache.
ContentCacheMixin (from mstrio.utils.cache) provides list_caches() and
delete_caches() helpers that operate against the /api/monitors/contentCaches
REST endpoint.

For report result caches and element/purge-all caching the equivalent
REST endpoints are used directly via the Connection object:
  - Report caches:  DELETE /api/v2/projects/{projectId}/caches/reportCaches
  - Purge all:      POST   /api/v2/projects/{projectId}/caches/purge
These correspond to the CM commands DELETE REPORT CACHES and PURGE ALL CACHING.

All three functions are non-fatal: an error is logged as a warning so that
the workflow can continue if, for example, there are simply no caches to delete.
"""

import logging
import traceback

from mstrio.connection import Connection
from mstrio.project_objects.content_cache import ContentCache
from mstrio.utils.cache import ContentCacheMixin

logger = logging.getLogger("sgb2_freigabe")


# ── Document / dossier caches ─────────────────────────────────────────────────

def delete_document_caches(conn: Connection, project_id: str, project_name: str) -> None:
    """
    Delete all document and dossier caches for a project.
    CM equivalent: DELETE DOCUMENT CACHES IN PROJECT "..."

    Uses the ContentCache API from mstrio.project_objects.content_cache.
    Errors are logged as warnings — never raised.
    """
    logger.info(f"  Deleting document caches for '{project_name}'...")
    try:
        caches: list[ContentCache] = ContentCacheMixin.list_caches(
            connection=conn,
            project_id=project_id,
        )
        if not caches:
            logger.info(f"  [OK] No document caches found for '{project_name}'")
            return

        deleted = 0
        for cache in caches:
            try:
                cache.delete(force=True)
                deleted += 1
            except Exception as exc:
                logger.warning(
                    f"  [WARN] Could not delete document cache '{cache.id}': {exc}"
                )

        logger.info(
            f"  [OK] Deleted {deleted}/{len(caches)} document cache(s) "
            f"for '{project_name}'"
        )

    except Exception as exc:
        logger.warning(
            f"  [WARN] delete_document_caches failed for '{project_name}': {exc}"
        )
        logger.debug(traceback.format_exc())


# ── Report result caches ──────────────────────────────────────────────────────

def delete_report_caches(conn: Connection, project_id: str, project_name: str) -> None:
    """
    Delete all report execution result caches for a project.
    CM equivalent: DELETE REPORT CACHES FROM PROJECT "..."

    Uses the REST API endpoint DELETE /api/v2/projects/{id}/caches/reportCaches
    directly through the Connection object.
    Errors are logged as warnings — never raised.
    """
    logger.info(f"  Deleting report caches for '{project_name}'...")
    original_project_id = conn.project_id
    try:
        conn.project_id = project_id

        response = conn.delete(
            url=f"{conn.base_url}api/v2/projects/{project_id}/caches/reportCaches",
        )

        if response.ok:
            logger.info(
                f"  [OK] Report caches deleted for '{project_name}' "
                f"(HTTP {response.status_code})"
            )
        else:
            logger.warning(
                f"  [WARN] Report cache deletion returned HTTP {response.status_code} "
                f"for '{project_name}': {response.text[:200]}"
            )

    except Exception as exc:
        logger.warning(
            f"  [WARN] delete_report_caches failed for '{project_name}': {exc}"
        )
        logger.debug(traceback.format_exc())
    finally:
        conn.project_id = original_project_id


# ── Purge all caching (element / hierarchy caches) ────────────────────────────

def purge_all_caching(conn: Connection, project_id: str, project_name: str) -> None:
    """
    Purge all element and hierarchy caches for a project.
    CM equivalent: PURGE ALL CACHING IN PROJECT "..."

    Uses the REST API endpoint POST /api/v2/projects/{id}/caches/purge
    directly through the Connection object.
    Errors are logged as warnings — never raised.
    """
    logger.info(f"  Purging all caches for '{project_name}'...")
    try:
        response = conn.post(
            url=f"{conn.base_url}api/v2/projects/{project_id}/caches/purge",
            json={},
        )

        if response.ok:
            logger.info(
                f"  [OK] All caches purged for '{project_name}' "
                f"(HTTP {response.status_code})"
            )
        else:
            logger.warning(
                f"  [WARN] Cache purge returned HTTP {response.status_code} "
                f"for '{project_name}': {response.text[:200]}"
            )

    except Exception as exc:
        logger.warning(
            f"  [WARN] purge_all_caching failed for '{project_name}': {exc}"
        )
        logger.debug(traceback.format_exc())


# ── Combined helper ───────────────────────────────────────────────────────────

def clear_all_project_caches(
    conn: Connection,
    project_id: str,
    project_name: str,
) -> None:
    """
    Run all three cache-clearing operations for a project in sequence:
      1. Delete report caches
      2. Purge all caching
      3. Delete document caches

    Mirrors the CM script block:
        DELETE REPORT CACHES FROM PROJECT "...";
        PURGE ALL CACHING IN PROJECT "...";
        DELETE DOCUMENT CACHES IN PROJECT "...";
    """
    delete_report_caches(conn, project_id, project_name)
    purge_all_caching(conn, project_id, project_name)
    delete_document_caches(conn, project_id, project_name)
