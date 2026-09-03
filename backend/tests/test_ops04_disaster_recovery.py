"""
OPS-04: real coverage for the disaster-recovery flow this item's runbook
(docs/Eivanta_Disaster_Recovery_Runbook_v1.0.docx) describes -- executable
proof of the exact procedure that document tells an operator to follow,
plus the two real numbers (RTO) and the one real risk (key escrow) that
document is built around, rather than either being asserted from memory.

Deliberately distinct from backend/tests/test_ops03_backup_restore.py:
that file unit-tests backend/backup.py's individual functions in
isolation (tiny synthetic files, tampering, retention math). This file
runs the FULL operator-facing recovery flow end to end against a
realistically-shaped multi-tenant dataset, and is the one that actually
measures wall-clock recovery time -- the runbook cites the numbers this
file measures, not a guess.
"""
import asyncio
import time
from datetime import date, timedelta

import pytest

from backend import backup
from backend.auth import hash_password


# A deliberately modest "realistic" synthetic dataset -- large enough to
# be more than a toy (multiple tenants, thousands of real ledger rows
# each with real INSERTs, not a single-row fixture) while still fast
# enough to run in CI on every commit. The runbook's own RTO section
# discloses explicitly that this is NOT validated against real production
# data volumes (none exist yet -- see the runbook's own Section 2) and
# that recovery time should be expected to scale with real file size.
SYNTHETIC_TENANT_COUNT = 5
SYNTHETIC_ROWS_PER_TENANT = 2000


def _write_ledger_csv(tmp_path, seed: str, n_rows: int) -> str:
    path = tmp_path / f"ledger_{seed}.csv"
    lines = ["date,category,amount,description"]
    base_date = date(2026, 1, 1)
    categories = ["Sales", "Hosting", "Payroll", "Marketing", "COGS"]
    for i in range(n_rows):
        d = base_date + timedelta(days=i % 300)
        cat = categories[i % len(categories)]
        amount = 100.0 + (i % 500)
        lines.append(f"{d.isoformat()},{cat},{amount:.2f},row {i} for {seed}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def _seed_realistic_dataset(isolated_db, tmp_path) -> dict:
    """Real tenants, real owners, real ingested ledger rows -- via the
    actual account-creation and ingestion code paths, not a hand-built
    DB fixture. Returns {"client_ids": [...], "total_rows": int}."""
    async def _seed():
        await isolated_db.init_db()
        client_ids = []
        for t in range(SYNTHETIC_TENANT_COUNT):
            client_id = f"OPS04-DR-TENANT-{t}"
            await isolated_db.create_tenant_and_owner(
                client_id, f"OPS-04 DR Test Co {t}", f"owner{t}@ops04-dr.test.example",
                hash_password("irrelevant-for-this-test"),
            )
            csv_path = _write_ledger_csv(tmp_path, f"t{t}", SYNTHETIC_ROWS_PER_TENANT)
            await isolated_db.ingest_csv_to_db(csv_path, client_id, original_filename=f"ledger_t{t}.csv")
            client_ids.append(client_id)
        return client_ids
    client_ids = asyncio.run(_seed())
    return {"client_ids": client_ids, "total_rows": SYNTHETIC_TENANT_COUNT * SYNTHETIC_ROWS_PER_TENANT}


# ---------------------------------------------------------------------
# The real, end-to-end recovery flow the runbook describes -- executed,
# not just narrated -- with real measured RTO.
# ---------------------------------------------------------------------

def test_full_disaster_recovery_flow_matches_the_runbook_and_measures_real_rto(isolated_db, tmp_path):
    seeded = _seed_realistic_dataset(isolated_db, tmp_path)
    backup_dir = tmp_path / "backups"

    # Step 1 of the runbook: a backup exists (this test creates one
    # directly; in production this would already be sitting in
    # EIVANTA_BACKUP_DIR from a prior manual/scheduled run).
    t0 = time.monotonic()
    meta = backup.create_backup(db_path=isolated_db.DB_PATH, backup_dir=str(backup_dir))
    backup_seconds = time.monotonic() - t0

    # The disaster: total loss of the live database file (the scenario
    # this runbook exists for -- disk corruption, accidental deletion,
    # a destroyed machine's file is unrecoverable by definition).
    from pathlib import Path
    Path(isolated_db.DB_PATH).unlink()
    assert not Path(isolated_db.DB_PATH).exists()

    # Step 2 of the runbook: locate the backup (list_backups), verify it
    # BEFORE trusting it (verify_backup), then restore. This is the
    # exact sequence the runbook's own Section 6 tells an operator to
    # run -- executed here for real, not just described.
    listed = backup.list_backups(str(backup_dir))
    assert listed[0]["filename"] == meta["filename"]

    check = backup.verify_backup(meta["filename"], backup_dir=str(backup_dir))
    assert check["verified"] is True

    t1 = time.monotonic()
    restore_result = backup.restore_backup(meta["filename"], target_db_path=isolated_db.DB_PATH, backup_dir=str(backup_dir))
    rto_seconds = time.monotonic() - t1

    assert restore_result["restored_to"] == isolated_db.DB_PATH
    assert Path(isolated_db.DB_PATH).exists()

    # Step 3 of the runbook: confirm the platform is actually usable
    # again -- real data for every seeded tenant, not just "the file
    # exists and DuckDB can open it."
    async def _confirm():
        results = []
        for client_id in seeded["client_ids"]:
            tenant = await isolated_db.get_tenant(client_id)
            history = await isolated_db.get_ingestion_history(client_id, limit=1)
            results.append((tenant is not None, len(history) == 1))
        return results
    confirmations = asyncio.run(_confirm())
    assert all(tenant_ok and history_ok for tenant_ok, history_ok in confirmations)

    # The real numbers the runbook's RTO section cites -- printed so a
    # test run's own output is the source, not a number typed once and
    # never re-checked. Deliberately no tight upper-bound assertion on
    # the exact seconds (this environment's disk/CPU speed is not the
    # runbook's subject -- the FLOW being correct and measurable is);
    # a generous ceiling still guards against a real performance
    # regression (e.g. an accidental O(n^2) change) going unnoticed.
    print(
        f"\n[OPS-04 RTO] backup: {backup_seconds:.3f}s, restore: {rto_seconds:.3f}s "
        f"for {seeded['total_rows']} ledger rows across {SYNTHETIC_TENANT_COUNT} tenants."
    )
    assert backup_seconds < 30.0, "backup took far longer than expected -- investigate before trusting this RTO figure"
    assert rto_seconds < 30.0, "restore took far longer than expected -- investigate before trusting this RTO figure"


def test_restore_preserves_a_corrupted_live_file_rather_than_only_deleting_it(isolated_db, tmp_path):
    """The other real disaster shape besides total loss: a live file
    that still EXISTS but is corrupted (a bad shutdown, a disk error) --
    confirms the runbook's own claim that restoring never destroys the
    evidence of what was there before, corrupted or not."""
    seeded = _seed_realistic_dataset(isolated_db, tmp_path)
    backup_dir = tmp_path / "backups"
    meta = backup.create_backup(db_path=isolated_db.DB_PATH, backup_dir=str(backup_dir))

    from pathlib import Path
    corrupted_bytes = b"\x00\x01\x02 this is not a valid duckdb file anymore"
    Path(isolated_db.DB_PATH).write_bytes(corrupted_bytes)

    result = backup.restore_backup(meta["filename"], target_db_path=isolated_db.DB_PATH, backup_dir=str(backup_dir))
    preserved = Path(result["preserved_previous_file"])
    assert preserved.read_bytes() == corrupted_bytes

    async def _confirm():
        return await isolated_db.get_tenant(seeded["client_ids"][0])
    assert asyncio.run(_confirm()) is not None


# ---------------------------------------------------------------------
# The central, disclosed risk this runbook exists to surface: recovery
# depends entirely on BACKUP_ENCRYPTION_KEY surviving whatever disaster
# took out the database. If the key lived only on the same machine, a
# full machine loss makes every backup permanently useless -- proven
# here, not just asserted in prose.
# ---------------------------------------------------------------------

def test_a_lost_encryption_key_makes_every_backup_permanently_unusable(isolated_db, tmp_path, monkeypatch):
    """Simulates the exact scenario the runbook's key-escrow warning is
    about: the machine holding BACKUP_ENCRYPTION_KEY is the SAME machine
    that was lost, and no copy was escrowed anywhere else. The backup
    file itself survives (it was already copied out, e.g. to a separate
    backup volume) but is now permanently undecryptable -- proving this
    is a real, provable failure mode, not a hypothetical."""
    seeded = _seed_realistic_dataset(isolated_db, tmp_path)
    backup_dir = tmp_path / "backups"
    meta = backup.create_backup(db_path=isolated_db.DB_PATH, backup_dir=str(backup_dir))

    # The disaster takes the database AND the only copy of the key with it.
    from pathlib import Path
    Path(isolated_db.DB_PATH).unlink()
    monkeypatch.delenv("BACKUP_ENCRYPTION_KEY", raising=False)

    check = backup.verify_backup(meta["filename"], backup_dir=str(backup_dir))
    assert check["verified"] is False

    # restore_backup calls verify_backup first (see its own docstring):
    # the RuntimeError _get_fernet() would raise on its own is caught
    # inside verify_backup and reported as verified=False, then
    # re-raised here as a ValueError wrapping that same reason -- one
    # consistent "fail closed with a real reason" shape for every
    # restore_backup failure, not two different exception types
    # depending on which underlying check failed.
    with pytest.raises(ValueError, match="BACKUP_ENCRYPTION_KEY"):
        backup.restore_backup(meta["filename"], target_db_path=isolated_db.DB_PATH, backup_dir=str(backup_dir))

    assert not Path(isolated_db.DB_PATH).exists(), "a key-loss failure must leave no partial/garbage file behind"


def test_recovery_succeeds_when_the_key_was_properly_escrowed_elsewhere(isolated_db, tmp_path, monkeypatch):
    """The contrast case: the SAME key, restored from a real escrow copy
    (simulated here by simply re-setting the env var to the original
    value, standing in for 'retrieved from the secrets manager/vault it
    was actually escrowed in') -- recovery succeeds. This is the whole
    point of the runbook's key-escrow recommendation made concrete: the
    only difference between total, permanent data loss and a successful
    recovery is whether this one value survived somewhere other than
    the machine that was lost."""
    seeded = _seed_realistic_dataset(isolated_db, tmp_path)
    backup_dir = tmp_path / "backups"
    meta = backup.create_backup(db_path=isolated_db.DB_PATH, backup_dir=str(backup_dir))

    import os
    escrowed_key = os.environ["BACKUP_ENCRYPTION_KEY"]  # stands in for "retrieved from real escrow"

    from pathlib import Path
    Path(isolated_db.DB_PATH).unlink()
    monkeypatch.delenv("BACKUP_ENCRYPTION_KEY", raising=False)
    assert backup.verify_backup(meta["filename"], backup_dir=str(backup_dir))["verified"] is False

    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", escrowed_key)
    result = backup.restore_backup(meta["filename"], target_db_path=isolated_db.DB_PATH, backup_dir=str(backup_dir))
    assert result["restored_to"] == isolated_db.DB_PATH

    async def _confirm():
        return await isolated_db.get_tenant(seeded["client_ids"][0])
    assert asyncio.run(_confirm()) is not None
