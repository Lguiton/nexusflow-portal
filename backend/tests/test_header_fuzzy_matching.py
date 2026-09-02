"""
DATA-02 (27 Aug 2026): ground-truth coverage for typo-tolerant header
matching (_fuzzy_resolve_header / _edit_distance) added on top of the
existing exact-match HEADER_ALIAS_MAP in db_manager.ingest_csv_to_db.

Why this matters beyond "nice to have": before this pass, a mistyped
header on category/date/description didn't error at all -- it silently
fell through to that column's existing default (Uncategorized / today /
a placeholder description) and the tenant's REAL column data for that
mistyped header was dropped without a trace. The fuzzy-match tests below
specifically assert the real data survives, not just that ingestion
"succeeds".

Also includes one explicit boundary test
(test_all_dates_unparseable_still_ingests_not_rejected) documenting a
schema-validation extension that was tried during development and
deliberately reverted -- see that test's own docstring.
"""
import pytest


def _row_by_description(rows, description):
    matches = [r for r in rows if r["description"] == description]
    assert len(matches) == 1, f"expected exactly 1 row with description={description!r}, found {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# Unit-level: _edit_distance / _fuzzy_resolve_header directly, no I/O.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("a,b,expected", [
    ("amount", "amount", 0),
    ("amuont", "amount", 1),      # adjacent transposition -- OSA, not plain Levenshtein
    ("catagory", "category", 1),  # single substitution
    ("descrption", "description", 1),  # single deletion (missing 'i')
    ("", "amount", 6),
    ("amount", "", 6),
])
def test_edit_distance_matches_expected(isolated_db, a, b, expected):
    assert isolated_db._edit_distance(a, b) == expected


@pytest.mark.parametrize("header,expected", [
    ("catagory", "category"),
    ("catgory", "category"),
    ("descrption", "description"),
    ("desciption", "description"),
    ("amuont", "amount"),
    ("txn_dat", "date"),         # typo of the existing 'txn_date' alias
    # Already handled by the exact alias map -- must NOT go through the
    # fuzzy path (returns None means "nothing to change", not "no match
    # exists"; the caller only overwrites the column when this is truthy).
    ("amount", None),
    ("amt", None),
    ("cat", None),
    # Genuinely unrelated -- must not collide with any known header.
    ("quantity", None),
    ("notes_internal_id_xyz", None),
    ("", None),
])
def test_fuzzy_resolve_header_matches_expected(isolated_db, header, expected):
    assert isolated_db._fuzzy_resolve_header(header) == expected


def test_fuzzy_resolve_header_returns_none_on_genuine_ambiguity(isolated_db):
    """A header equidistant from two DIFFERENT canonical targets must be
    left unresolved -- guessing wrong here would misfile a whole column
    of real tenant data under the wrong field."""
    tiny_vocab = {"cost": "cost", "cast": "unrelated_target", "amount": "amount"}
    original = isolated_db._KNOWN_HEADER_VOCAB
    isolated_db._KNOWN_HEADER_VOCAB = tiny_vocab
    try:
        # 'cust' is edit-distance 1 from BOTH 'cost' and 'cast'.
        assert isolated_db._fuzzy_resolve_header("cust") is None
    finally:
        isolated_db._KNOWN_HEADER_VOCAB = original


# ---------------------------------------------------------------------------
# End-to-end: real CSV ingestion through the fuzzy-matched header.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_typo_category_header_preserves_real_data_not_default(tmp_path, isolated_db):
    """Before this pass: a mistyped 'category' header silently defaulted
    every row to 'Uncategorized' and the tenant's real category values
    were gone. Now: the header is fuzzy-matched and the real values
    survive."""
    db = isolated_db
    path = tmp_path / "typo_category.csv"
    path.write_text(
        "date,catagory,amount,description\n"
        "2026-01-05,Marketing,-500,typo-category-row\n",
        encoding="utf-8",
    )
    msg = await db.ingest_csv_to_db(str(path), "CLI-TEST")
    assert "'catagory' -> 'category'" in msg
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    row = _row_by_description(rows, "typo-category-row")
    assert row["category"] == "Marketing"  # NOT "Uncategorized"


@pytest.mark.asyncio
async def test_typo_description_header_preserves_real_data_not_placeholder(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "typo_description.csv"
    path.write_text(
        "date,category,amount,descrption\n"
        "2026-01-05,Sales,1000,This is the real note\n",
        encoding="utf-8",
    )
    msg = await db.ingest_csv_to_db(str(path), "CLI-TEST")
    assert "'descrption' -> 'description'" in msg
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    matches = [r for r in rows if r["category"] == "Sales"]
    assert len(matches) == 1
    assert matches[0]["description"] == "This is the real note"  # NOT the placeholder


@pytest.mark.asyncio
async def test_typo_amount_header_now_succeeds_where_it_previously_would_reject(tmp_path, isolated_db):
    """'amuont' matches nothing in the exact alias map -- before this
    pass, this file would hit the "CSV must contain a recognized amount
    column" rejection outright."""
    db = isolated_db
    path = tmp_path / "typo_amount.csv"
    path.write_text(
        "date,category,amuont,description\n"
        "2026-01-05,Sales,2500,typo-amount-row\n",
        encoding="utf-8",
    )
    msg = await db.ingest_csv_to_db(str(path), "CLI-TEST")
    assert "Successfully ingested 1 records" in msg
    assert "'amuont' -> 'amount'" in msg
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    row = _row_by_description(rows, "typo-amount-row")
    assert row["amount"] == 2500.0


@pytest.mark.asyncio
async def test_exact_alias_header_unaffected_no_fuzzy_disclosure(tmp_path, isolated_db):
    """Regression guard: a header already resolved by the EXACT alias map
    (HEADER_ALIAS_MAP, pre-existing DATA-02 behavior) must behave exactly
    as before -- no fuzzy-match note in the message, since nothing fuzzy
    happened."""
    db = isolated_db
    path = tmp_path / "exact_alias.csv"
    path.write_text(
        "date,cat,amt,description\n"
        "2026-01-05,Rent,-750,exact-alias-row\n",
        encoding="utf-8",
    )
    msg = await db.ingest_csv_to_db(str(path), "CLI-TEST")
    assert "typo-tolerant match" not in msg
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    row = _row_by_description(rows, "exact-alias-row")
    assert row["category"] == "Rent"
    assert row["amount"] == -750.0


@pytest.mark.asyncio
async def test_unrelated_extra_header_not_fuzzy_matched_and_ignored(tmp_path, isolated_db):
    """An extra column that isn't close to any known header (typo or
    otherwise) must not be forced into some canonical column -- it's just
    ignored, same as an unrecognized extra column always was."""
    db = isolated_db
    path = tmp_path / "extra_column.csv"
    path.write_text(
        "date,category,amount,description,internal_reference_code\n"
        "2026-01-05,Sales,100,extra-col-row,XJ-99182\n",
        encoding="utf-8",
    )
    msg = await db.ingest_csv_to_db(str(path), "CLI-TEST")
    assert "Successfully ingested 1 records" in msg
    assert "typo-tolerant match" not in msg
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    row = _row_by_description(rows, "extra-col-row")
    assert row["category"] == "Sales"
    assert row["amount"] == 100.0


@pytest.mark.asyncio
async def test_multiple_typo_headers_all_disclosed_together(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "multi_typo.csv"
    path.write_text(
        "date,catagory,amount,descrption\n"
        "2026-01-05,Payroll,-3000,multi-typo-row\n",
        encoding="utf-8",
    )
    msg = await db.ingest_csv_to_db(str(path), "CLI-TEST")
    assert "'catagory' -> 'category'" in msg
    assert "'descrption' -> 'description'" in msg
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    row = _row_by_description(rows, "multi-typo-row")
    assert row["category"] == "Payroll"



@pytest.mark.asyncio
async def test_all_dates_unparseable_still_ingests_not_rejected(tmp_path, isolated_db):
    """
    Explicit boundary test, not a new behavior: DATA-02 deliberately does
    NOT extend the amount check's "100% unparseable -> reject" reasoning
    to date, because an already-shipped, already-tested feature depends
    on ingestion succeeding here -- virtual_cfo.generate_cfo_briefing's
    distinct NO_DATEABLE_DATA status (see
    test_virtual_cfo_evidence.py::test_no_dateable_data_status_when_every_row_unparseable).
    This was tried during development and reverted after the full
    regression suite caught the conflict; asserted here directly so a
    future change to this file can't silently reintroduce it.
    """
    db = isolated_db
    path = tmp_path / "all_bad_dates.csv"
    path.write_text(
        "date,category,amount,description\n"
        "not-a-date,Sales,100,row-one\n"
        "also-garbage,Sales,200,row-two\n",
        encoding="utf-8",
    )
    msg = await db.ingest_csv_to_db(str(path), "CLI-TEST")
    assert "Successfully ingested 2 records" in msg
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    assert len(rows) == 2
