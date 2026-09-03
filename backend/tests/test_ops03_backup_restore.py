"""
OPS-03: real coverage for backend/backup.py -- backup creation,
Fernet encryption, checksum-verified restore tests, destructive restore
(with its own previous-file preservation), and retention pruning.

Every test here uses tmp_path for both the "database" file and the
backup directory (never the real backend/backups/ or backend/eivanta.duckdb)
and the fixed BACKUP_ENCRYPTION_KEY conftest.py sets for the whole suite
-- never backend/.env's real deployed key.
"""
import asyncio
import time

import pytest

from backend import backup


def _make_fake_db(tmp_path, content: bytes = b"not a real duckdb file, just real bytes to round-trip") -> str:
    """A real file on disk with real, known bytes -- backup.py never
    parses the DuckDB format itself, only copies/encrypts/decrypts raw
    bytes, so a plain file stands in for a real .duckdb file perfectly
    well for every test except the one integration test at the bottom
    that uses a REAL isolated DuckDB with real tenant rows."""
    db_path = tmp_path / "fake.duckdb"
    db_path.write_bytes(content)
    return str(db_path)


# ---------------------------------------------------------------------
# create_backup
# ---------------------------------------------------------------------

def test_create_backup_raises_for_nonexistent_db_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup.create_backup(db_path=str(tmp_path / "does-not-exist.duckdb"), backup_dir=str(tmp_path / "backups"))


def test_create_backup_produces_a_file_that_is_not_plaintext(tmp_path):
    secret_marker = b"PASSWORD_HASH_LOOKING_CONTENT_1234567890"
    db_path = _make_fake_db(tmp_path, secret_marker)
    backup_dir = tmp_path / "backups"

    meta = backup.create_backup(db_path=db_path, backup_dir=str(backup_dir))
    raw_backup_bytes = (backup_dir / meta["filename"]).read_bytes()

    assert secret_marker not in raw_backup_bytes, "backup file must be encrypted, not a plaintext copy"
    assert meta["plaintext_size_bytes"] == len(secret_marker)
    assert len(meta["sha256"]) == 64  # real hex sha256


def test_create_backup_writes_a_readable_metadata_sidecar(tmp_path):
    import json
    db_path = _make_fake_db(tmp_path)
    backup_dir = tmp_path / "backups"

    meta = backup.create_backup(db_path=db_path, backup_dir=str(backup_dir))
    sidecar = json.loads((backup_dir / f"{meta['filename']}.meta.json").read_text())
    assert sidecar == meta


def test_missing_encryption_key_fails_loudly_not_silently(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKUP_ENCRYPTION_KEY", raising=False)
    db_path = _make_fake_db(tmp_path)
    with pytest.raises(RuntimeError, match="BACKUP_ENCRYPTION_KEY"):
        backup.create_backup(db_path=db_path, backup_dir=str(tmp_path / "backups"))
    # And confirms it failed BEFORE writing anything -- no half-created backup left behind.
    assert not (tmp_path / "backups").exists() or list((tmp_path / "backups").glob("*")) == []


def test_a_malformed_encryption_key_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "not-a-real-fernet-key")
    db_path = _make_fake_db(tmp_path)
    with pytest.raises(RuntimeError, match="not a valid Fernet key"):
        backup.create_backup(db_path=db_path, backup_dir=str(tmp_path / "backups"))


# ---------------------------------------------------------------------
# verify_backup: the real, non-destructive "restore test"
# ---------------------------------------------------------------------

def test_verify_backup_true_for_an_untampered_backup(tmp_path):
    db_path = _make_fake_db(tmp_path)
    backup_dir = tmp_path / "backups"
    meta = backup.create_backup(db_path=db_path, backup_dir=str(backup_dir))

    result = backup.verify_backup(meta["filename"], backup_dir=str(backup_dir))
    assert result == {"filename": meta["filename"], "verified": True, "reason": None}


def test_verify_backup_false_for_a_missing_file(tmp_path):
    result = backup.verify_backup("eivanta_backup_never_existed.duckdb.enc", backup_dir=str(tmp_path / "backups"))
    assert result["verified"] is False
    assert "not found" in result["reason"].lower()


def test_verify_backup_false_for_tampered_ciphertext(tmp_path):
    db_path = _make_fake_db(tmp_path)
    backup_dir = tmp_path / "backups"
    meta = backup.create_backup(db_path=db_path, backup_dir=str(backup_dir))

    backup_path = backup_dir / meta["filename"]
    raw = bytearray(backup_path.read_bytes())
    raw[10] ^= 0xFF  # flip a real byte in the middle of the ciphertext
    backup_path.write_bytes(bytes(raw))

    result = backup.verify_backup(meta["filename"], backup_dir=str(backup_dir))
    assert result["verified"] is False
    assert result["reason"]  # a real, specific reason, not silently swallowed


def test_verify_backup_false_when_the_encryption_key_was_rotated(tmp_path, monkeypatch):
    db_path = _make_fake_db(tmp_path)
    backup_dir = tmp_path / "backups"
    meta = backup.create_backup(db_path=db_path, backup_dir=str(backup_dir))

    from cryptography.fernet import Fernet
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())

    result = backup.verify_backup(meta["filename"], backup_dir=str(backup_dir))
    assert result["verified"] is False


def test_verify_backup_false_for_checksum_mismatch_in_metadata(tmp_path):
    """Simulates a metadata file that's been hand-edited/corrupted
    independently of the ciphertext -- verify must catch a mismatch
    between the decrypted content and the RECORDED checksum, not just
    trust that Fernet decrypted successfully."""
    import json
    db_path = _make_fake_db(tmp_path)
    backup_dir = tmp_path / "backups"
    meta = backup.create_backup(db_path=db_path, backup_dir=str(backup_dir))

    meta_path = backup_dir / f"{meta['filename']}.meta.json"
    corrupted = json.loads(meta_path.read_text())
    corrupted["sha256"] = "0" * 64
    meta_path.write_text(json.dumps(corrupted))

    result = backup.verify_backup(meta["filename"], backup_dir=str(backup_dir))
    assert result["verified"] is False
    assert "checksum" in result["reason"].lower()


# ---------------------------------------------------------------------
# restore_backup: destructive, but verify-first and previous-file-preserving
# ---------------------------------------------------------------------

def test_restore_round_trips_content_byte_identical(tmp_path):
    original_content = b"real bytes that must survive backup -> restore exactly, including \x00 nulls \xff"
    db_path = _make_fake_db(tmp_path, original_content)
    backup_dir = tmp_path / "backups"
    meta = backup.create_backup(db_path=db_path, backup_dir=str(backup_dir))

    restore_target = tmp_path / "restored.duckdb"
    result = backup.restore_backup(meta["filename"], target_db_path=str(restore_target), backup_dir=str(backup_dir))

    assert restore_target.read_bytes() == original_content
    assert result["restored_to"] == str(restore_target)
    assert result["preserved_previous_file"] is None  # nothing existed at the target before


def test_restore_refuses_a_tampered_backup_and_raises(tmp_path):
    db_path = _make_fake_db(tmp_path)
    backup_dir = tmp_path / "backups"
    meta = backup.create_backup(db_path=db_path, backup_dir=str(backup_dir))
    backup_path = backup_dir / meta["filename"]
    raw = bytearray(backup_path.read_bytes())
    raw[5] ^= 0xFF
    backup_path.write_bytes(bytes(raw))

    restore_target = tmp_path / "restored.duckdb"
    with pytest.raises(ValueError):
        backup.restore_backup(meta["filename"], target_db_path=str(restore_target), backup_dir=str(backup_dir))
    assert not restore_target.exists(), "a refused restore must never write anything to the target"


def test_restore_preserves_the_previous_target_file_instead_of_deleting_it(tmp_path):
    db_path = _make_fake_db(tmp_path, b"new content to restore")
    backup_dir = tmp_path / "backups"
    meta = backup.create_backup(db_path=db_path, backup_dir=str(backup_dir))

    restore_target = tmp_path / "live.duckdb"
    old_content = b"the currently-live database content, must not be silently deleted"
    restore_target.write_bytes(old_content)

    result = backup.restore_backup(meta["filename"], target_db_path=str(restore_target), backup_dir=str(backup_dir))

    assert restore_target.read_bytes() == b"new content to restore"
    preserved_path = result["preserved_previous_file"]
    assert preserved_path is not None
    from pathlib import Path
    assert Path(preserved_path).read_bytes() == old_content
    assert "pre-restore" in preserved_path


# ---------------------------------------------------------------------
# list_backups / apply_retention_policy
# ---------------------------------------------------------------------

def test_list_backups_returns_newest_first(tmp_path):
    db_path = _make_fake_db(tmp_path)
    backup_dir = tmp_path / "backups"
    filenames = []
    for _ in range(3):
        meta = backup.create_backup(db_path=db_path, backup_dir=str(backup_dir))
        filenames.append(meta["filename"])
        time.sleep(0.01)  # real, distinct timestamps

    listed = backup.list_backups(str(backup_dir))
    assert [m["filename"] for m in listed] == list(reversed(filenames))


def test_retention_policy_keeps_n_most_recent_and_deletes_the_rest(tmp_path):
    db_path = _make_fake_db(tmp_path)
    backup_dir = tmp_path / "backups"
    filenames = []
    for _ in range(5):
        meta = backup.create_backup(db_path=db_path, backup_dir=str(backup_dir))
        filenames.append(meta["filename"])
        time.sleep(0.01)

    result = backup.apply_retention_policy(str(backup_dir), keep_count=2)

    assert set(result["kept"]) == set(filenames[-2:])  # 2 most recent
    assert set(result["deleted"]) == set(filenames[:-2])
    remaining = backup.list_backups(str(backup_dir))
    assert len(remaining) == 2
    for meta in result["deleted"]:
        assert not (backup_dir / meta).exists()


def test_retention_policy_leaves_unreadable_foreign_files_alone(tmp_path):
    db_path = _make_fake_db(tmp_path)
    backup_dir = tmp_path / "backups"
    backup.create_backup(db_path=db_path, backup_dir=str(backup_dir))

    foreign = backup_dir / "some_other_file.txt"
    foreign.write_text("not a backup, unrelated file that happens to live in this directory")

    backup.apply_retention_policy(str(backup_dir), keep_count=0)
    assert foreign.exists(), "retention must never touch a file it didn't create/recognize"


def test_retention_keep_count_zero_deletes_every_real_backup(tmp_path):
    db_path = _make_fake_db(tmp_path)
    backup_dir = tmp_path / "backups"
    for _ in range(3):
        backup.create_backup(db_path=db_path, backup_dir=str(backup_dir))
        time.sleep(0.01)

    result = backup.apply_retention_policy(str(backup_dir), keep_count=0)
    assert result["kept"] == []
    assert len(result["deleted"]) == 3
    assert backup.list_backups(str(backup_dir)) == []


# ---------------------------------------------------------------------
# Integration: a REAL isolated DuckDB with real tenant rows, round-tripped
# ---------------------------------------------------------------------

def test_backup_and_restore_round_trips_a_real_tenants_data(isolated_db, tmp_path):
    """The end-to-end case that actually matters: back up a real
    DuckDB file created through the real account-creation path, wipe it,
    restore from the backup, and confirm the real tenant/user row comes
    back byte-for-byte-equivalent (verified via a real query against the
    restored file, not just a raw byte comparison)."""
    from backend.auth import hash_password

    async def _seed():
        await isolated_db.init_db()
        return await isolated_db.create_tenant_and_owner(
            "OPS03-BACKUP-TENANT", "OPS-03 Backup Test Co", "owner@ops03-backup.test.example",
            hash_password("irrelevant-for-this-test"),
        )
    created_user = asyncio.run(_seed())

    backup_dir = tmp_path / "backups"
    meta = backup.create_backup(db_path=isolated_db.DB_PATH, backup_dir=str(backup_dir))
    assert backup.verify_backup(meta["filename"], backup_dir=str(backup_dir))["verified"] is True

    # Simulate real data loss: wipe the live file entirely.
    from pathlib import Path
    Path(isolated_db.DB_PATH).unlink()

    result = backup.restore_backup(meta["filename"], target_db_path=isolated_db.DB_PATH, backup_dir=str(backup_dir))
    assert result["restored_to"] == isolated_db.DB_PATH

    async def _read_back():
        return await isolated_db.get_tenant("OPS03-BACKUP-TENANT")
    restored_tenant = asyncio.run(_read_back())

    assert restored_tenant is not None
    assert restored_tenant["client_id"] == "OPS03-BACKUP-TENANT"

    async def _read_user():
        return await isolated_db.get_user_by_email("owner@ops03-backup.test.example")
    restored_user = asyncio.run(_read_user())
    assert restored_user is not None
    assert restored_user["user_id"] == created_user["user_id"]
