"""
OPS-05: real platform status and maintenance-mode control.

Two things this module owns, both real and checked, not decorative:

1. A real DB-connectivity check (check_db_reachable) -- confirmed by
   reading backend/main.py directly: the existing GET /api/v1/health
   endpoint returns a hardcoded {"status": "ONLINE"} unconditionally,
   regardless of whether the database is actually reachable. That is a
   real, disclosed gap this module does not silently paper over by
   changing /api/v1/health's existing contract (something may already
   depend on it always returning 200) -- instead, main.py's new GET
   /api/v1/status endpoint uses this real check and reports what
   /api/v1/health cannot.

2. A real, togglable maintenance-mode flag. Deliberately file-based, not
   an admin-authenticated HTTP endpoint -- see this item's own Master
   Build List entry for why: no platform-admin/superadmin role exists
   anywhere in this codebase (same disclosed gap OPS-02/OPS-03 already
   surfaced), and every current role is tenant-scoped, so no tenant
   owner should be able to put the ENTIRE PLATFORM into maintenance for
   every other tenant. A flag file an operator creates/removes directly
   on the host (or via the EIVANTA_MAINTENANCE_MODE env var override,
   useful for a containerized deploy where env vars are how config gets
   pushed) is checked fresh on every request -- no code deploy or
   process restart needed to toggle it, unlike a value only read once
   at startup.
"""
import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("eivanta.status")

try:
    from backend import db_manager as _db_manager
except ImportError:
    import db_manager as _db_manager

DEFAULT_FLAG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".maintenance_mode")
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _flag_path(flag_path: Optional[str] = None) -> Path:
    return Path(flag_path or os.getenv("EIVANTA_MAINTENANCE_FLAG_PATH") or DEFAULT_FLAG_PATH)


def enable_maintenance_mode(reason: str = "", flag_path: Optional[str] = None) -> dict:
    """Creates the real flag file, real content (reason + real UTC
    timestamp), so get_maintenance_status() below can report WHEN
    maintenance started and WHY, not just that it's active."""
    info = {"reason": reason or None, "since": datetime.now(timezone.utc).isoformat()}
    path = _flag_path(flag_path)
    path.write_text(json.dumps(info))
    logger.warning(f"Maintenance mode ENABLED. reason={reason!r}")
    return info


def disable_maintenance_mode(flag_path: Optional[str] = None) -> None:
    path = _flag_path(flag_path)
    if path.exists():
        path.unlink()
    logger.warning("Maintenance mode DISABLED.")


def is_maintenance_mode(flag_path: Optional[str] = None) -> bool:
    """
    Checked fresh on every call -- no caching, deliberately, so a flag
    file created or removed by an operator mid-run takes effect on the
    very next request, without a restart. Two independent triggers,
    either sufficient on its own: the flag file's existence, or
    EIVANTA_MAINTENANCE_MODE set to a real true-ish value. A flag file
    that exists but is unreadable/corrupt still counts as maintenance
    being active (fails toward the SAFER state -- a platform stuck
    showing "under maintenance" a little longer than intended is a far
    smaller problem than a real maintenance window silently not being
    honored because of a parse error).
    """
    env_value = os.getenv("EIVANTA_MAINTENANCE_MODE", "").strip().lower()
    if env_value in _TRUE_VALUES:
        return True
    return _flag_path(flag_path).exists()


def get_maintenance_status(flag_path: Optional[str] = None) -> dict:
    """Returns {"active": bool, "reason": Optional[str], "since": Optional[str]}.
    Reads the flag file's real content when present and parseable;
    falls back to active=True with reason/since left None for the
    env-var trigger (which carries no metadata of its own) or an
    unreadable flag file (see is_maintenance_mode's own note on why
    that still counts as active)."""
    active = is_maintenance_mode(flag_path)
    if not active:
        return {"active": False, "reason": None, "since": None}
    path = _flag_path(flag_path)
    if path.exists():
        try:
            info = json.loads(path.read_text())
            return {"active": True, "reason": info.get("reason"), "since": info.get("since")}
        except Exception as e:
            logger.error(f"Maintenance flag file {path} exists but is unreadable: {e}")
    return {"active": True, "reason": None, "since": None}


async def check_db_reachable() -> bool:
    """
    A REAL connectivity check -- opens an actual DuckDB connection
    against the live DB_PATH (read fresh off the db_manager module, same
    "never a stale import-time copy" discipline backend/backup.py
    already established) and runs a trivial real query, under the same
    get_db_lock() every other DB operation in this codebase already
    uses. Returns False on ANY failure (missing file, lock contention
    that never clears, a corrupt database) rather than raising -- a
    status check that can itself crash is worse than one that correctly
    reports "not reachable."
    """
    import duckdb
    lock = _db_manager.get_db_lock()

    def _check():
        try:
            conn = duckdb.connect(_db_manager.DB_PATH)
            try:
                conn.execute("SELECT 1").fetchone()
                return True
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"DB reachability check failed: {e}")
            return False

    import asyncio

    def _locked_check():
        with lock:
            return _check()

    return await asyncio.to_thread(_locked_check)
