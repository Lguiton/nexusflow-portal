"""
Real tests for db_manager.ingest_csv_to_db / _read_csv_or_raise (DATA-03,
DATA-04, DATA-06, FIN-01's recurring-flag parsing). Calls the DB-layer
function directly (fast, precise) rather than only going through the HTTP
endpoint -- test_api_endpoints.py covers the HTTP-layer wiring (auth,
status codes) separately, with one end-to-end upload test tying both
layers together.
"""
import pytest


@pytest.mark.asyncio
async def test_valid_csv_ingests_all_rows(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "ledger.csv"
    path.write_text(
        "date,category,amount,description\n"
        "2026-01-05,Sales,1000,Widget sale\n"
        "2026-01-10,Rent,-500,Office rent\n"
        "2026-01-15,Sales,2500.50,Widget sale 2\n",
        encoding="utf-8",
    )
    msg = await db.ingest_csv_to_db(str(path), "CLI-TEST")
    assert "Successfully ingested 3 records" in msg

    context = await db.get_ledger_chart_context("CLI-TEST")
    assert context["row_count"] == 3
    assert context["unparseable_date_count"] == 0
    total = sum(c["total_amount"] for c in context["category_breakdown"])
    assert total == pytest.approx(3000.50)


@pytest.mark.asyncio
async def test_empty_file_rejected(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        await db.ingest_csv_to_db(str(path), "CLI-TEST")


@pytest.mark.asyncio
async def test_header_only_file_rejected(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "header_only.csv"
    path.write_text("date,category,amount,description\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header row but no data rows"):
        await db.ingest_csv_to_db(str(path), "CLI-TEST")


@pytest.mark.asyncio
async def test_ragged_csv_rejected_with_actionable_message(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "ragged.csv"
    # Row 2 has an extra field -- pandas' C parser raises ParserError for this.
    path.write_text(
        "date,category,amount,description\n"
        "2026-01-05,Sales,1000,Widget sale\n"
        "2026-01-10,Rent,-500,Office rent,EXTRA_FIELD\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="could not be parsed as a valid CSV"):
        await db.ingest_csv_to_db(str(path), "CLI-TEST")


@pytest.mark.asyncio
async def test_duplicate_columns_after_normalization_rejected(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "dupe_cols.csv"
    # "Amount" and "amount" normalize (strip+lower) to the same name.
    path.write_text(
        "date,category,Amount,amount,description\n"
        "2026-01-05,Sales,1000,1000,Widget sale\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate column"):
        await db.ingest_csv_to_db(str(path), "CLI-TEST")


@pytest.mark.asyncio
async def test_missing_amount_column_rejected_no_guessing(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "no_amount.csv"
    path.write_text(
        "date,category,quantity,description\n"
        "2026-01-05,Sales,42,Widget sale\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="recognized amount column"):
        await db.ingest_csv_to_db(str(path), "CLI-TEST")


@pytest.mark.asyncio
async def test_revenue_expense_columns_combine_into_amount(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "rev_exp.csv"
    path.write_text(
        "date,category,revenue,expense,description\n"
        "2026-01-05,Sales,1000,200,Net widget sale\n",
        encoding="utf-8",
    )
    await db.ingest_csv_to_db(str(path), "CLI-TEST")
    rows = await db.get_ledger_rows("CLI-TEST")
    assert rows["rows"][0]["amount"] == pytest.approx(800.0)


@pytest.mark.asyncio
async def test_dollar_comma_and_parenthetical_negative_amounts_parsed(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "formatted_amounts.csv"
    path.write_text(
        "date,category,amount,description\n"
        '2026-01-05,Sales,"$1,250.00",Widget sale\n'
        '2026-01-06,Rent,"($500.00)",Office rent\n',
        encoding="utf-8",
    )
    await db.ingest_csv_to_db(str(path), "CLI-TEST")
    rows = {r["description"]: r["amount"] for r in (await db.get_ledger_rows("CLI-TEST"))["rows"]}
    assert rows["Widget sale"] == pytest.approx(1250.00)
    assert rows["Office rent"] == pytest.approx(-500.00)


@pytest.mark.asyncio
async def test_all_unparseable_amounts_rejected_not_silently_zero(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "bad_amounts.csv"
    path.write_text(
        "date,category,amount,description\n"
        "2026-01-05,Sales,not_a_number,Widget sale\n"
        "2026-01-06,Rent,also_bad,Office rent\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unparseable amount"):
        await db.ingest_csv_to_db(str(path), "CLI-TEST")


@pytest.mark.asyncio
async def test_partial_bad_amounts_skipped_not_rejected(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "partial_bad.csv"
    path.write_text(
        "date,category,amount,description\n"
        "2026-01-05,Sales,1000,Good row\n"
        "2026-01-06,Rent,garbage,Bad row\n",
        encoding="utf-8",
    )
    msg = await db.ingest_csv_to_db(str(path), "CLI-TEST")
    assert "Successfully ingested 1 records" in msg
    assert "Skipped 1 row" in msg


@pytest.mark.asyncio
async def test_missing_category_date_description_get_real_defaults(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "minimal.csv"
    path.write_text("amount\n100\n", encoding="utf-8")
    await db.ingest_csv_to_db(str(path), "CLI-TEST")
    row = (await db.get_ledger_rows("CLI-TEST"))["rows"][0]
    assert row["category"] == "Uncategorized"
    assert row["description"] == "Uploaded ledger entry"


@pytest.mark.parametrize("token,expected", [
    ("true", True), ("Yes", True), ("1", True), ("subscription", True),
    ("false", False), ("No", False), ("0", False), ("one-time", False),
    ("garbage_value", None), ("", None),
])
@pytest.mark.asyncio
async def test_recurring_flag_tokens_parsed_correctly(tmp_path, isolated_db, token, expected):
    db = isolated_db
    path = tmp_path / "recurring.csv"
    path.write_text(
        f'date,category,amount,description,is_recurring\n2026-01-05,Sales,100,Row,"{token}"\n',
        encoding="utf-8",
    )
    await db.ingest_csv_to_db(str(path), "CLI-TEST")
    row = (await db.get_ledger_rows("CLI-TEST"))["rows"][0]
    assert row["is_recurring"] is expected


@pytest.mark.asyncio
async def test_row_cap_rejected(tmp_path, isolated_db, monkeypatch):
    db = isolated_db
    # Patch the cap down instead of generating 500k+ real rows -- exercises
    # the exact same code path (`len(df) > MAX_INGEST_ROWS`) cheaply.
    monkeypatch.setattr(db, "MAX_INGEST_ROWS", 2)
    path = tmp_path / "too_many_rows.csv"
    path.write_text(
        "date,category,amount,description\n"
        "2026-01-01,Sales,1,r1\n2026-01-02,Sales,1,r2\n2026-01-03,Sales,1,r3\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="row.*limit"):
        await db.ingest_csv_to_db(str(path), "CLI-TEST")


@pytest.mark.asyncio
async def test_reupload_replaces_not_appends(tmp_path, isolated_db):
    db = isolated_db
    path1 = tmp_path / "first.csv"
    path1.write_text("date,category,amount,description\n2026-01-01,Sales,100,First\n", encoding="utf-8")
    await db.ingest_csv_to_db(str(path1), "CLI-TEST")

    path2 = tmp_path / "second.csv"
    path2.write_text("date,category,amount,description\n2026-01-02,Sales,200,Second\n", encoding="utf-8")
    await db.ingest_csv_to_db(str(path2), "CLI-TEST")

    context = await db.get_ledger_chart_context("CLI-TEST")
    assert context["row_count"] == 1  # replaced, not appended
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    assert rows[0]["description"] == "Second"


@pytest.mark.asyncio
async def test_identical_reupload_flagged_in_message(tmp_path, isolated_db):
    db = isolated_db
    path = tmp_path / "same.csv"
    path.write_text("date,category,amount,description\n2026-01-01,Sales,100,Row\n", encoding="utf-8")
    await db.ingest_csv_to_db(str(path), "CLI-TEST")
    # Re-upload the byte-identical file again.
    msg = await db.ingest_csv_to_db(str(path), "CLI-TEST")
    assert "identical to your last successful upload" in msg


@pytest.mark.asyncio
async def test_tenant_isolation_on_ingest(tmp_path, isolated_db):
    db = isolated_db
    path_a = tmp_path / "a.csv"
    path_a.write_text("date,category,amount,description\n2026-01-01,Sales,100,Tenant A row\n", encoding="utf-8")
    path_b = tmp_path / "b.csv"
    path_b.write_text("date,category,amount,description\n2026-01-01,Sales,999,Tenant B row\n", encoding="utf-8")

    await db.ingest_csv_to_db(str(path_a), "CLI-A")
    await db.ingest_csv_to_db(str(path_b), "CLI-B")

    ctx_a = await db.get_ledger_chart_context("CLI-A")
    ctx_b = await db.get_ledger_chart_context("CLI-B")
    assert ctx_a["row_count"] == 1
    assert ctx_b["row_count"] == 1
    assert ctx_a["category_breakdown"][0]["total_amount"] == pytest.approx(100)
    assert ctx_b["category_breakdown"][0]["total_amount"] == pytest.approx(999)
