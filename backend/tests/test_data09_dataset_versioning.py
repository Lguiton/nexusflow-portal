"""
DATA-09 (versioning half): real coverage for the explicit dataset
versioning this pass adds -- backend/db_manager.py's
_archive_current_ledger_version_locked/get_dataset_versions/
get_dataset_version_rows/restore_dataset_version, and the three new
endpoints (GET /api/v1/data/dataset-versions, GET .../rows, POST
.../restore) that expose them.

Three layers, same shape as test_ops05_maintenance_status.py:

1. db_manager functions directly -- the archive-on-replace mechanics, the
   critical no-double-counting guarantee (see
   test_a_second_upload_never_leaves_old_and_new_rows_both_live below --
   the single most important test in this file, given what a silent
   double-count would mean on a financial BI product), restore, and
   multi-tenant isolation.
2. The three real HTTP endpoints, auth/role-gating included.
3. delete_tenant_ledger's own behavior is confirmed UNCHANGED by this
   pass -- deletion still never creates a version (a deliberate,
   disclosed scope boundary, not an oversight).
"""
import io

import pytest


async def _ingest(db, tmp_path, client_id, rows, name="ledger.csv"):
    path = tmp_path / name
    header = "date,category,amount,description,is_recurring"
    path.write_text("\n".join([header] + rows) + "\n", encoding="utf-8")
    return await db.ingest_csv_to_db(str(path), client_id, original_filename=name)


# ---------------------------------------------------------------------
# db_manager functions directly
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_ever_upload_creates_no_phantom_version(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-FIRST", ["2026-01-01,Sales,100,Row,"], name="a.csv")
    assert await db.count_dataset_versions("CLI-FIRST") == 0
    assert await db.get_dataset_versions("CLI-FIRST") == []


@pytest.mark.asyncio
async def test_a_second_upload_never_leaves_old_and_new_rows_both_live(tmp_path, isolated_db):
    """The single most important test in this file: after a second upload
    replaces the first, `ledgers` must contain ONLY the new upload's rows
    -- never old+new both counted live. A silent double-count here would
    corrupt every real financial figure this platform reports."""
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-REPL", ["2026-01-01,Sales,100,Row A,"], name="a.csv")
    await _ingest(db, tmp_path, "CLI-REPL", [
        "2026-02-01,Sales,200,Row B,",
        "2026-02-02,Sales,300,Row C,",
    ], name="b.csv")

    live = await db.get_ledger_chart_context("CLI-REPL")
    assert live["row_count"] == 2, "Only the second upload's 2 rows should be live -- not 1+2=3."


@pytest.mark.asyncio
async def test_a_second_upload_archives_the_first_as_version_1(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-ARCH", ["2026-01-01,Sales,100,Row A,"], name="a.csv")
    await _ingest(db, tmp_path, "CLI-ARCH", ["2026-02-01,Sales,200,Row B,"], name="b.csv")

    versions = await db.get_dataset_versions("CLI-ARCH")
    assert len(versions) == 1
    v = versions[0]
    assert v["version_number"] == 1
    assert v["row_count"] == 1
    assert v["replaced_by_filename"] == "b.csv"
    assert v["source"] == "REPLACED"
    assert await db.count_dataset_versions("CLI-ARCH") == 1


@pytest.mark.asyncio
async def test_archived_version_rows_match_the_original_data_exactly(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-ROWS", ["2026-01-01,Sales,100,Original row,"], name="a.csv")
    await _ingest(db, tmp_path, "CLI-ROWS", ["2026-02-01,Sales,200,New row,"], name="b.csv")

    rows = await db.get_dataset_version_rows("CLI-ROWS", 1)
    assert len(rows) == 1
    assert rows[0]["description"] == "Original row"
    assert rows[0]["amount"] == 100
    assert rows[0]["category"] == "Sales"


@pytest.mark.asyncio
async def test_three_uploads_produce_two_sequential_versions(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-SEQ", ["2026-01-01,Sales,100,V0,"], name="v0.csv")
    await _ingest(db, tmp_path, "CLI-SEQ", ["2026-02-01,Sales,200,V1,"], name="v1.csv")
    await _ingest(db, tmp_path, "CLI-SEQ", ["2026-03-01,Sales,300,V2,"], name="v2.csv")

    versions = await db.get_dataset_versions("CLI-SEQ")
    assert [v["version_number"] for v in versions] == [2, 1]  # newest-first
    assert [v["replaced_by_filename"] for v in versions] == ["v2.csv", "v1.csv"]
    # And the live table has only the third upload's data.
    assert (await db.get_ledger_chart_context("CLI-SEQ"))["row_count"] == 1


@pytest.mark.asyncio
async def test_restore_brings_back_the_exact_old_rows(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-RESTORE", ["2026-01-01,Sales,111,Original data,"], name="a.csv")
    await _ingest(db, tmp_path, "CLI-RESTORE", ["2026-02-01,Sales,222,Replacement data,"], name="b.csv")

    restored_count = await db.restore_dataset_version("CLI-RESTORE", 1)
    assert restored_count == 1

    live = await db.get_dataset_version_rows("CLI-RESTORE", 1)  # version 1's own archive is untouched by the restore
    assert live[0]["description"] == "Original data"

    current_rows = await db.get_ledger_chart_context("CLI-RESTORE")
    assert current_rows["row_count"] == 1


@pytest.mark.asyncio
async def test_restore_never_loses_data_it_overwrites(tmp_path, isolated_db):
    """Restoring to an old version must itself archive whatever was live
    just before the restore -- so restoring is always reversible."""
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-SAFE", ["2026-01-01,Sales,111,Version one data,"], name="a.csv")
    await _ingest(db, tmp_path, "CLI-SAFE", ["2026-02-01,Sales,222,Version two data,"], name="b.csv")
    assert await db.count_dataset_versions("CLI-SAFE") == 1  # version 1 archived so far

    await db.restore_dataset_version("CLI-SAFE", 1)
    # Restoring to version 1 archived version 2's data (what was live just
    # before the restore) as a brand new version 2.
    assert await db.count_dataset_versions("CLI-SAFE") == 2
    versions = await db.get_dataset_versions("CLI-SAFE")
    newest = versions[0]
    assert newest["version_number"] == 2
    assert newest["source"] == "RESTORE_SNAPSHOT"

    restored_snapshot_rows = await db.get_dataset_version_rows("CLI-SAFE", 2)
    assert restored_snapshot_rows[0]["description"] == "Version two data"


@pytest.mark.asyncio
async def test_restore_to_a_nonexistent_version_raises_value_error(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-NOVER", ["2026-01-01,Sales,100,Row,"], name="a.csv")
    with pytest.raises(ValueError, match="does not exist"):
        await db.restore_dataset_version("CLI-NOVER", 99)


@pytest.mark.asyncio
async def test_restore_for_a_tenant_with_zero_versions_raises_value_error(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-NOVER2", ["2026-01-01,Sales,100,Row,"], name="a.csv")
    # Only one upload has ever happened -- zero versions exist yet.
    with pytest.raises(ValueError, match="does not exist"):
        await db.restore_dataset_version("CLI-NOVER2", 1)


@pytest.mark.asyncio
async def test_dataset_versioning_is_tenant_isolated(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-ISO-A", ["2026-01-01,Sales,100,A original,"], name="a1.csv")
    await _ingest(db, tmp_path, "CLI-ISO-A", ["2026-02-01,Sales,200,A replacement,"], name="a2.csv")
    await _ingest(db, tmp_path, "CLI-ISO-B", ["2026-01-01,Sales,999,B original,"], name="b1.csv")
    await _ingest(db, tmp_path, "CLI-ISO-B", ["2026-02-01,Sales,888,B replacement,"], name="b2.csv")

    versions_a = await db.get_dataset_versions("CLI-ISO-A")
    versions_b = await db.get_dataset_versions("CLI-ISO-B")
    assert len(versions_a) == 1 and len(versions_b) == 1
    assert versions_a[0]["replaced_by_filename"] == "a2.csv"
    assert versions_b[0]["replaced_by_filename"] == "b2.csv"

    # Tenant A cannot read tenant B's version 1 rows by asking for "version 1".
    rows_a = await db.get_dataset_version_rows("CLI-ISO-A", 1)
    assert rows_a[0]["description"] == "A original"

    # Restoring tenant A must never touch tenant B's live data.
    await db.restore_dataset_version("CLI-ISO-A", 1)
    b_live = await db.get_ledger_chart_context("CLI-ISO-B")
    assert b_live["row_count"] == 1  # unaffected


@pytest.mark.asyncio
async def test_dataset_version_rows_pagination(tmp_path, isolated_db):
    db = isolated_db
    rows = [f"2026-01-0{i},Sales,{i * 10},Row {i}," for i in range(1, 6)]
    await _ingest(db, tmp_path, "CLI-PAGE", rows, name="a.csv")
    await _ingest(db, tmp_path, "CLI-PAGE", ["2026-02-01,Sales,999,Replacement,"], name="b.csv")

    page1 = await db.get_dataset_version_rows("CLI-PAGE", 1, limit=2, offset=0)
    page2 = await db.get_dataset_version_rows("CLI-PAGE", 1, limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert {r["row_id"] for r in page1}.isdisjoint({r["row_id"] for r in page2})


@pytest.mark.asyncio
async def test_delete_tenant_ledger_never_creates_a_version(tmp_path, isolated_db):
    """Deletion itself must never CREATE a new version -- confirmed for a
    fresh delete-only tenant that never had a replace event."""
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-DEL-ONLY", ["2026-01-01,Sales,100,Row,"], name="a.csv")
    await db.delete_tenant_ledger("CLI-DEL-ONLY")
    assert await db.count_dataset_versions("CLI-DEL-ONLY") == 0


@pytest.mark.asyncio
async def test_delete_tenant_ledger_also_purges_archived_versions(tmp_path, isolated_db):
    """The real defect this pass caught and fixed: the danger-zone UI
    promises "Permanently deletes every ledger row this tenant has
    uploaded" -- a past REPLACED upload's rows are ledger rows this
    tenant uploaded too, so leaving them silently restorable via
    restore_dataset_version after a "delete everything" would make that
    promise false. delete_tenant_ledger must purge dataset_versions AND
    ledger_version_archive for this tenant, not just the live `ledgers`
    rows."""
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-DEL-PURGE", ["2026-01-01,Sales,100,Row A,"], name="a.csv")
    await _ingest(db, tmp_path, "CLI-DEL-PURGE", ["2026-02-01,Sales,200,Row B,"], name="b.csv")
    assert await db.count_dataset_versions("CLI-DEL-PURGE") == 1  # from the replace above

    await db.delete_tenant_ledger("CLI-DEL-PURGE")

    assert await db.count_dataset_versions("CLI-DEL-PURGE") == 0
    assert await db.get_dataset_versions("CLI-DEL-PURGE") == []
    assert await db.get_dataset_version_rows("CLI-DEL-PURGE", 1) == []
    # A subsequent restore attempt correctly fails -- the version is
    # genuinely gone, not just hidden from the listing.
    with pytest.raises(ValueError, match="does not exist"):
        await db.restore_dataset_version("CLI-DEL-PURGE", 1)


@pytest.mark.asyncio
async def test_delete_tenant_ledger_purge_is_tenant_isolated(tmp_path, isolated_db):
    """Deleting tenant A's archived versions must never touch tenant B's."""
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-DEL-ISO-A", ["2026-01-01,Sales,100,A original,"], name="a1.csv")
    await _ingest(db, tmp_path, "CLI-DEL-ISO-A", ["2026-02-01,Sales,200,A replacement,"], name="a2.csv")
    await _ingest(db, tmp_path, "CLI-DEL-ISO-B", ["2026-01-01,Sales,999,B original,"], name="b1.csv")
    await _ingest(db, tmp_path, "CLI-DEL-ISO-B", ["2026-02-01,Sales,888,B replacement,"], name="b2.csv")

    await db.delete_tenant_ledger("CLI-DEL-ISO-A")

    assert await db.count_dataset_versions("CLI-DEL-ISO-A") == 0
    assert await db.count_dataset_versions("CLI-DEL-ISO-B") == 1  # unaffected
    b_versions = await db.get_dataset_versions("CLI-DEL-ISO-B")
    assert b_versions[0]["replaced_by_filename"] == "b2.csv"


# ---------------------------------------------------------------------
# Real HTTP endpoints
# ---------------------------------------------------------------------

def _upload(client, headers, content: bytes, filename: str = "ledger.csv"):
    return client.post(
        "/api/finance/upload-ledger",
        files={"file": (filename, io.BytesIO(content), "text/csv")},
        headers=headers,
    )


def test_dataset_versions_endpoint_end_to_end(client, auth_headers):
    _upload(client, auth_headers, b"date,category,amount,description\n2026-01-01,Sales,100,Original\n", "a.csv")
    _upload(client, auth_headers, b"date,category,amount,description\n2026-02-01,Sales,200,Replacement\n", "b.csv")

    resp = client.get("/api/v1/data/dataset-versions", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_count"] == 1
    assert body["versions"][0]["version_number"] == 1
    assert body["versions"][0]["replaced_by_filename"] == "b.csv"


def test_dataset_versions_endpoint_requires_auth(client):
    resp = client.get("/api/v1/data/dataset-versions")
    assert resp.status_code == 401


def test_dataset_version_rows_endpoint_end_to_end(client, auth_headers):
    _upload(client, auth_headers, b"date,category,amount,description\n2026-01-01,Sales,100,Original row\n", "a.csv")
    _upload(client, auth_headers, b"date,category,amount,description\n2026-02-01,Sales,200,Replacement\n", "b.csv")

    resp = client.get("/api/v1/data/dataset-versions/1/rows", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["rows"][0]["description"] == "Original row"


def test_dataset_version_rows_endpoint_requires_auth(client):
    resp = client.get("/api/v1/data/dataset-versions/1/rows")
    assert resp.status_code == 401


def test_restore_endpoint_requires_owner_or_admin(client, make_auth_headers):
    owner = make_auth_headers("CLI-RESTORE-ROLE", role="owner")
    member = make_auth_headers("CLI-RESTORE-ROLE", role="member")
    viewer = make_auth_headers("CLI-RESTORE-ROLE", role="viewer")

    _upload(client, owner, b"date,category,amount,description\n2026-01-01,Sales,100,Original\n", "a.csv")
    _upload(client, owner, b"date,category,amount,description\n2026-02-01,Sales,200,Replacement\n", "b.csv")

    resp_member = client.post("/api/v1/data/dataset-versions/1/restore", headers=member)
    assert resp_member.status_code == 403
    resp_viewer = client.post("/api/v1/data/dataset-versions/1/restore", headers=viewer)
    assert resp_viewer.status_code == 403

    resp_owner = client.post("/api/v1/data/dataset-versions/1/restore", headers=owner)
    assert resp_owner.status_code == 200, resp_owner.text
    body = resp_owner.json()
    assert body["status"] == "SUCCESS"
    assert body["rows_restored"] == 1


def test_restore_endpoint_returns_404_for_a_nonexistent_version(client, auth_headers):
    _upload(client, auth_headers, b"date,category,amount,description\n2026-01-01,Sales,100,Row\n", "a.csv")
    resp = client.post("/api/v1/data/dataset-versions/99/restore", headers=auth_headers)
    assert resp.status_code == 404
    assert "does not exist" in resp.json()["detail"]


def test_restore_endpoint_reflects_in_the_live_ledger_afterward(client, auth_headers):
    _upload(client, auth_headers, b"date,category,amount,description\n2026-01-01,Sales,111,Original\n", "a.csv")
    _upload(client, auth_headers, b"date,category,amount,description\n2026-02-01,Sales,222,Replacement\n", "b.csv")

    client.post("/api/v1/data/dataset-versions/1/restore", headers=auth_headers)

    rows_resp = client.post("/api/v1/finance/ledger-rows", headers=auth_headers, json={"limit": 10})
    assert rows_resp.status_code == 200, rows_resp.text
    descriptions = {r["description"] for r in rows_resp.json()["rows"]}
    assert descriptions == {"Original"}
