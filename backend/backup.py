"""
OPS-03: real backup creation, retention pruning, and restore-verification
for the platform's single shared DuckDB file.

IMPORTANT scope note, load-bearing for every function below: this
codebase has ONE DuckDB file per deployment (db_manager.py's DB_PATH),
shared by every tenant and scoped only by a client_id column inside each
table -- not one file per tenant (see db_manager.py's own get_db_lock
module docstring for the concurrency model this assumes). That means
backup/restore here is necessarily WHOLE-DATABASE, not tenant-scoped --
there is no such thing yet as "restore just this one tenant's data"
without a real per-tenant export/import tool this module does not build.
It also means this is NOT exposed as a tenant-facing HTTP endpoint: every
existing role (owner/admin/member/viewer) is tenant-scoped, and none of
them should be able to overwrite every OTHER tenant's data by restoring a
platform-wide backup. A real platform-admin/superadmin role concept does
not exist anywhere in this codebase yet -- a genuine, disclosed gap (see
this item's own Master Build List entry) standing in the way of a safe
authenticated HTTP surface for this. Until then, these are real,
independently tested library functions an operator runs directly (a
script, a cron job, a manual shell), the same "real and tested, honestly
scoped" bar as everything else in this codebase, just not wired to a
public route.

Encryption: Fernet (symmetric, from the `cryptography` package, already a
dependency via backend/byok.py). Deliberately a SEPARATE key
(BACKUP_ENCRYPTION_KEY) from byok.py's BYOK_ENCRYPTION_KEY -- a backup is
a copy of the ENTIRE database (password hashes, refresh-token hashes,
every tenant's BYOK ciphertext, MFA secrets, real ledger data), not just
one tenant's BYOK key, so rotating one key must never silently affect the
other. Same "refuse to start with a missing/malformed key rather than
silently fall back to an insecure default" discipline byok.py and
backend/auth.py's JWT_SECRET already established (SEC-01) -- lazy, so a
deployment that never calls create_backup/restore_backup/verify_backup is
never blocked by a key it doesn't yet need.

Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
and put it in backend/.env as BACKUP_ENCRYPTION_KEY=<the output>.
"""
import os
import json
import shutil
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

logger = logging.getLogger("eivanta.backup")

try:
    from backend import db_manager as _db_manager
except ImportError:
    import db_manager as _db_manager

# Reads db_manager.DB_PATH fresh at CALL time (via the module reference
# above), never a name bound once at import time -- same "read fresh off
# the module" discipline backend/main.py's SEC-02 rate-limit wiring
# already established, for the same reason: db_manager.DB_PATH can be
# monkeypatched (backend/tests/conftest.py's isolated_db fixture does
# exactly this, pointing every test at its own throwaway DB file), and a
# stale import-time copy would silently keep targeting the wrong file.

DEFAULT_BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
# A reasonable starting default, not derived from real operational data
# yet -- same disclosed-default convention as MAX_FAILED_LOGIN_ATTEMPTS
# (backend/accounts.py) and the rate-limit constants (backend/rate_limit.py).
DEFAULT_RETENTION_COUNT = 14

BACKUP_FILENAME_PREFIX = "eivanta_backup_"
BACKUP_FILENAME_SUFFIX = ".duckdb.enc"
METADATA_SUFFIX = ".meta.json"


def _get_fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        raise RuntimeError(
            "Backups require the 'cryptography' package. Run: pip install -r requirements.txt"
        ) from e
    raw_key = os.getenv("BACKUP_ENCRYPTION_KEY")
    if not raw_key:
        raise RuntimeError(
            "BACKUP_ENCRYPTION_KEY is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "and add it to backend/.env. Deliberately a SEPARATE key from "
            "BYOK_ENCRYPTION_KEY -- see this module's own docstring for why."
        )
    try:
        return Fernet(raw_key.encode() if isinstance(raw_key, str) else raw_key)
    except Exception as e:
        raise RuntimeError(f"BACKUP_ENCRYPTION_KEY is not a valid Fernet key: {e}") from e


def _resolve_backup_dir(backup_dir: Optional[str]) -> Path:
    d = Path(backup_dir or os.getenv("EIVANTA_BACKUP_DIR") or DEFAULT_BACKUP_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_backup(db_path: Optional[str] = None, backup_dir: Optional[str] = None) -> dict:
    """
    Real backup: copies the live DuckDB file's bytes under the SAME lock
    every other read/write in this codebase already goes through
    (db_manager.get_db_lock()) -- without it, a backup started
    concurrently with a write could copy a torn, inconsistent file.
    Encrypts the copy with Fernet BEFORE it ever touches disk as a
    backup -- see this module's docstring for why an unencrypted backup
    would be a strictly WORSE security posture than the live file.

    Returns a metadata dict: filename, created_at (UTC ISO 8601),
    plaintext_size_bytes, sha256 (of the PLAINTEXT DB content -- so a
    later verify/restore can prove the decrypted bytes are exactly what
    was backed up, not just that Fernet's own authentication accepted
    the token), source_db_path. The same dict is also written alongside
    the encrypted backup as a plain-JSON `.meta.json` sidecar (never
    encrypted itself -- it holds no secret, and list_backups/verify_backup
    need to read it without the key).

    Raises FileNotFoundError if there's no DB file at all yet to back up
    (a brand-new install before init_db() has ever run) -- a real,
    honest failure, not a silently-empty backup.
    """
    src = Path(db_path or _db_manager.DB_PATH)
    if not src.exists():
        raise FileNotFoundError(f"No database file found at {src} -- nothing to back up yet.")

    fernet = _get_fernet()  # fail before ever touching the lock/reading the file if misconfigured
    lock = _db_manager.get_db_lock()
    with lock:
        plaintext = src.read_bytes()

    checksum = hashlib.sha256(plaintext).hexdigest()
    ciphertext = fernet.encrypt(plaintext)

    ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%dT%H%M%S%f") + "Z"
    filename = f"{BACKUP_FILENAME_PREFIX}{stamp}{BACKUP_FILENAME_SUFFIX}"
    out_dir = _resolve_backup_dir(backup_dir)
    backup_path = out_dir / filename
    backup_path.write_bytes(ciphertext)

    metadata = {
        "filename": filename,
        "created_at": ts.isoformat(),
        "plaintext_size_bytes": len(plaintext),
        "sha256": checksum,
        "source_db_path": str(src),
    }
    (out_dir / f"{filename}{METADATA_SUFFIX}").write_text(json.dumps(metadata, indent=2))
    logger.info(f"Backup created: {filename} ({len(plaintext)} plaintext bytes).")
    return metadata


def list_backups(backup_dir: Optional[str] = None) -> list:
    """
    Real listing, newest first, built from the real `.meta.json` sidecar
    files on disk -- deliberately NOT a database table: a backup's own
    catalog must stay readable even when the thing that's broken is the
    live database itself. Skips (and logs, never raises for) a metadata
    file that's unreadable/corrupt, or whose matching encrypted backup
    file has gone missing -- a partial/orphaned pair is left out of the
    listing rather than reported as a usable backup.
    """
    out_dir = _resolve_backup_dir(backup_dir)
    entries = []
    for meta_path in out_dir.glob(f"{BACKUP_FILENAME_PREFIX}*{METADATA_SUFFIX}"):
        try:
            meta = json.loads(meta_path.read_text())
            backup_path = out_dir / meta["filename"]
            if backup_path.exists():
                entries.append(meta)
            else:
                logger.error(f"Backup metadata {meta_path} references missing file {meta['filename']} -- skipped.")
        except Exception as e:
            logger.error(f"Skipping unreadable backup metadata file {meta_path}: {e}")
    entries.sort(key=lambda m: m["created_at"], reverse=True)
    return entries


def verify_backup(filename: str, backup_dir: Optional[str] = None) -> dict:
    """
    A REAL restore test that never touches the live database: decrypts
    the named backup fully into memory and confirms its SHA-256 matches
    the checksum recorded at backup time. This makes the "restore tests"
    half of this item's title real and automatable (e.g. a scheduled job
    could call this immediately after every create_backup) without
    needing a second live database to actually restore into every time.

    Returns {"filename", "verified": bool, "reason": Optional[str]}.
    Fails CLOSED, by design: every failure mode (missing backup file,
    missing/corrupt metadata, a wrong or rotated encryption key, a
    tampered ciphertext that fails Fernet's own built-in authentication
    check, a checksum mismatch) is caught and reported as
    verified=False with a real, specific reason -- never raised past
    this function, and never silently treated as a pass.
    """
    out_dir = _resolve_backup_dir(backup_dir)
    backup_path = out_dir / filename
    meta_path = out_dir / f"{filename}{METADATA_SUFFIX}"
    try:
        if not backup_path.exists():
            return {"filename": filename, "verified": False, "reason": "Backup file not found."}
        if not meta_path.exists():
            return {"filename": filename, "verified": False, "reason": "Backup metadata file not found."}
        meta = json.loads(meta_path.read_text())
        fernet = _get_fernet()
        ciphertext = backup_path.read_bytes()
        plaintext = fernet.decrypt(ciphertext)  # raises InvalidToken on tampering or a wrong/rotated key
        checksum = hashlib.sha256(plaintext).hexdigest()
        if checksum != meta.get("sha256"):
            return {
                "filename": filename, "verified": False,
                "reason": "Checksum mismatch -- decrypted content does not match the recorded backup.",
            }
        return {"filename": filename, "verified": True, "reason": None}
    except Exception as e:
        return {"filename": filename, "verified": False, "reason": f"{type(e).__name__}: {e}"}


def restore_backup(filename: str, target_db_path: Optional[str] = None, backup_dir: Optional[str] = None) -> dict:
    """
    Real, destructive restore -- OVERWRITES target_db_path (defaults to
    the live DB_PATH) with the decrypted contents of the named backup.

    Verifies BEFORE writing anything (see verify_backup): a
    tampered/corrupt/wrong-key backup is refused outright, raising
    ValueError, rather than partially overwriting the live database with
    garbage first and discovering the problem after.

    The existing target file, if any, is renamed aside with a real
    `.pre-restore-<UTC timestamp>` suffix rather than deleted -- a
    restore must never itself be the operation that makes data loss
    irreversible. Same lock discipline as create_backup: the swap
    happens under db_manager.get_db_lock() so no concurrent read/write
    can observe a half-written target file.

    See this module's own top-of-file docstring for why this is
    deliberately whole-database, not tenant-scoped.
    """
    check = verify_backup(filename, backup_dir=backup_dir)
    if not check["verified"]:
        raise ValueError(f"Refusing to restore '{filename}': {check['reason']}")

    out_dir = _resolve_backup_dir(backup_dir)
    backup_path = out_dir / filename
    fernet = _get_fernet()
    plaintext = fernet.decrypt(backup_path.read_bytes())

    target = Path(target_db_path or _db_manager.DB_PATH)
    lock = _db_manager.get_db_lock()
    preserved = None
    with lock:
        if target.exists():
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "Z"
            preserved = target.with_name(f"{target.name}.pre-restore-{ts}")
            shutil.move(str(target), str(preserved))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(plaintext)

    logger.warning(f"Database restored from backup '{filename}' to {target}.")
    return {
        "filename": filename,
        "restored_to": str(target),
        "preserved_previous_file": str(preserved) if preserved else None,
    }


def apply_retention_policy(backup_dir: Optional[str] = None, keep_count: int = DEFAULT_RETENTION_COUNT) -> dict:
    """
    Real pruning: keeps the `keep_count` most recent backups (by
    created_at, via list_backups' own newest-first ordering) and deletes
    both the encrypted file and its metadata sidecar for every backup
    beyond that. Never deletes a file it can't first find valid,
    matching metadata for -- an unreadable or foreign file sitting in
    the backup directory is left alone, not guessed at.

    Returns {"kept": [filenames], "deleted": [filenames]}.
    """
    entries = list_backups(backup_dir)  # newest first
    keep_count = max(0, int(keep_count))
    to_keep = entries[:keep_count]
    to_delete = entries[keep_count:]
    out_dir = _resolve_backup_dir(backup_dir)
    deleted = []
    for meta in to_delete:
        filename = meta["filename"]
        backup_path = out_dir / filename
        meta_path = out_dir / f"{filename}{METADATA_SUFFIX}"
        for p in (backup_path, meta_path):
            if p.exists():
                p.unlink()
        deleted.append(filename)
    if deleted:
        logger.info(f"Retention policy pruned {len(deleted)} backup(s), kept {len(to_keep)}.")
    return {"kept": [m["filename"] for m in to_keep], "deleted": deleted}
