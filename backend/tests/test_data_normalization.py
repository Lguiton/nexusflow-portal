"""
DATA-07: ground-truth coverage for db_manager.py's encoding/date/currency/
NULL/precision normalization rules -- each test pins an exact input to an
exact expected output, rather than just checking "it didn't crash", since
this item is specifically about correctness of the normalization, not just
absence of errors.
"""
import pytest


def _row_by_description(rows, description):
    matches = [r for r in rows if r["description"] == description]
    assert len(matches) == 1, f"expected exactly 1 row with description={description!r}, found {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# Date normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw_date,expected_iso", [
    ("2026-01-05", "2026-01-05"),
    ("2026/01/05", "2026-01-05"),
    ("01/05/2026", "2026-01-05"),   # MM/DD/YYYY -- resolved first
    ("13/05/2026", "2026-05-13"),   # 13 can't be a month -> falls through to DD/MM/YYYY
    ("01-05-2026", "2026-01-05"),   # MM-DD-YYYY
    ("01/05/26", "2026-01-05"),     # MM/DD/YY
    ("Jan 5, 2026", "2026-01-05"),
    ("January 5, 2026", "2026-01-05"),
    ("5 Jan 2026", "2026-01-05"),
    ("5 January 2026", "2026-01-05"),
    ("5-Jan-2026", "2026-01-05"),
    ("5-Jan-26", "2026-01-05"),
])
@pytest.mark.asyncio
async def test_date_formats_normalize_to_iso(tmp_path, isolated_db, raw_date, expected_iso):
    db = isolated_db
    path = tmp_path / "dates.csv"
    # raw_date is quoted -- several cases (e.g. "Jan 5, 2026") contain a
    # comma, which would otherwise split into an extra CSV field.
    path.write_text(
        f'date,category,amount,description\n"{raw_date}",Sales,100,date-format-case\n',
        encoding="utf-8",
    )
    await db.ingest_csv_to_db(str(path), "CLI-TEST")
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    row = _row_by_description(rows, "date-format-case")
    assert row["date"] == expected_iso, f"{raw_date!r} normalized to {row['date']!r}, expected {expected_iso!r}"


@pytest.mark.asyncio
async def test_unparseable_date_stored_as_null_row_still_kept(tmp_path, isolated_db):
    """A row with a genuinely unrecognizable date isn't dropped -- its
    amount/category/description are still real data -- but its date comes
    back NULL rather than a guessed or garbage value, and the caller is
    told about it in the response message."""
    db = isolated_db
    path = tmp_path / "bad_date.csv"
    path.write_text(
        "date,category,amount,description\n"
        "not-a-real-date,Sales,250,bad-date-row\n"
        "2026-01-05,Sales,100,good-date-row\n",
        encoding="utf-8",
    )
    msg = await db.ingest_csv_to_db(str(path), "CLI-TEST")
    assert "Successfully ingested 2 records" in msg
    assert "1 row(s) had a date value" in msg

    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    bad_row = _row_by_description(rows, "bad-date-row")
    good_row = _row_by_description(rows, "good-date-row")
    assert bad_row["date"] is None
    assert bad_row["amount"] == 250
    assert good_row["date"] == "2026-01-05"

    context = await db.get_ledger_chart_context("CLI-TEST")
    assert context["row_count"] == 2
    assert context["unparseable_date_count"] == 1


@pytest.mark.asyncio
async def test_missing_date_still_defaults_to_today_unchanged_behavior(tmp_path, isolated_db):
    """Pre-existing behavior (not part of this item's scope) -- a MISSING
    date still defaults to today, distinct from a PRESENT-but-unparseable
    one, which is genuinely new in this pass."""
    from datetime import date as date_cls
    db = isolated_db
    path = tmp_path / "no_date_col.csv"
    path.write_text("category,amount,description\nSales,100,no-date-column-row\n", encoding="utf-8")
    await db.ingest_csv_to_db(str(path), "CLI-TEST")
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    row = _row_by_description(rows, "no-date-column-row")
    assert row["date"] == date_cls.today().isoformat()


# ---------------------------------------------------------------------------
# Currency normalization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_currency_symbols_all_strip_correctly(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "currency.csv"
    path.write_text(
        "date,category,amount,description\n"
        '2026-01-05,Sales,"$1,000.00",dollar-row\n'
        "2026-01-05,Sales,€500.00,euro-row\n"
        "2026-01-05,Sales,£250.50,pound-row\n"
        "2026-01-05,Sales,¥100,yen-row\n"
        "2026-01-05,Rent,(120.00),paren-negative-row\n",
        encoding="utf-8",
    )
    await db.ingest_csv_to_db(str(path), "CLI-TEST")
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    assert _row_by_description(rows, "dollar-row")["amount"] == 1000.00
    assert _row_by_description(rows, "euro-row")["amount"] == 500.00
    assert _row_by_description(rows, "pound-row")["amount"] == 250.50
    assert _row_by_description(rows, "yen-row")["amount"] == 100.00
    assert _row_by_description(rows, "paren-negative-row")["amount"] == -120.00


# ---------------------------------------------------------------------------
# Precision normalization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revenue_minus_expense_rounds_cleanly_to_two_decimals(tmp_path, isolated_db):
    """revenue-expense subtraction is a classic source of floating-point
    drift (e.g. 19.1 - 19.0 == 0.09999999999999964 in raw IEEE-754) -- the
    stored amount must come back as a clean 2-decimal value, not a drifted
    one."""
    db = isolated_db
    path = tmp_path / "precision.csv"
    path.write_text(
        "date,category,revenue,expense,description\n"
        "2026-01-05,Sales,19.10,19.00,precision-row\n",
        encoding="utf-8",
    )
    await db.ingest_csv_to_db(str(path), "CLI-TEST")
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    row = _row_by_description(rows, "precision-row")
    assert row["amount"] == 0.10
    assert row["amount"] == pytest.approx(0.10, abs=1e-9)


# ---------------------------------------------------------------------------
# Encoding normalization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cp1252_encoded_file_ingests_with_correct_characters(tmp_path, isolated_db):
    """A real Windows-origin export (Excel 'CSV' save, typically
    Windows-1252) -- previously any non-UTF-8 byte sequence failed the
    whole upload outright."""
    db = isolated_db
    path = tmp_path / "cp1252.csv"
    content = "date,category,amount,description\n2026-01-05,Sales,100,Café “order”\n"
    path.write_bytes(content.encode("cp1252"))
    msg = await db.ingest_csv_to_db(str(path), "CLI-TEST")
    assert "Successfully ingested 1 records" in msg
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    assert "Café" in rows[0]["description"]


@pytest.mark.asyncio
async def test_latin1_encoded_file_ingests_with_correct_characters(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "latin1.csv"
    content = "date,category,amount,description\n2026-01-05,Sales,100,Bjørn's ledger\n"
    path.write_bytes(content.encode("latin-1"))
    msg = await db.ingest_csv_to_db(str(path), "CLI-TEST")
    assert "Successfully ingested 1 records" in msg
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    assert "Bjørn" in rows[0]["description"]


@pytest.mark.asyncio
async def test_utf8_multibyte_characters_still_decode_correctly(tmp_path, isolated_db):
    """Regression guard: UTF-8 is tried FIRST, so a genuinely UTF-8 file
    with a multi-byte character must not be mis-decoded by a later
    fallback encoding (which would otherwise turn 'café' into mojibake
    like 'cafÃ©')."""
    db = isolated_db
    path = tmp_path / "utf8.csv"
    content = "date,category,amount,description\n2026-01-05,Sales,100,café\n"
    path.write_bytes(content.encode("utf-8"))
    await db.ingest_csv_to_db(str(path), "CLI-TEST")
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    assert rows[0]["description"] == "café"


@pytest.mark.asyncio
async def test_genuinely_undecodable_bytes_still_raise_actionable_error(tmp_path, isolated_db):
    """latin-1 accepts literally any byte sequence, so the fallback chain
    must never mask a truly broken file (e.g. a binary file uploaded by
    mistake) as a successful-but-garbled ingest of financial data -- a
    non-CSV-shaped result should still fail with a clear parser error,
    not silently 'succeed' with garbage rows."""
    db = isolated_db
    path = tmp_path / "binary.csv"
    path.write_bytes(bytes(range(0, 40)) * 20)
    with pytest.raises(ValueError):
        await db.ingest_csv_to_db(str(path), "CLI-TEST")
