"""
Real tests for the read/query and mutation functions in db_manager.py that
sit behind the DIFF-0x / FIN-0x endpoints: MRR (FIN-01), forecast accuracy
(FIN-04), ledger row drill-down (DIFF-01), category suggestions (DIFF-06),
ingestion history (DATA-08), and tenant-scoped deletion (DATA-09).
"""
from datetime import date, timedelta

import pytest


def _this_month_date(day: int = 5) -> str:
    """A real date string guaranteed to fall in the current calendar month
    -- get_mrr_summary and get_forecast_accuracy are both explicitly
    scoped to "this calendar month", so tests need a genuinely current
    date rather than a hardcoded one that will silently stop matching."""
    today = date.today()
    return today.replace(day=min(day, 28)).isoformat()


async def _ingest(db, tmp_path, client_id, rows, name="ledger.csv"):
    path = tmp_path / name
    header = "date,category,amount,description,is_recurring"
    path.write_text("\n".join([header] + rows) + "\n", encoding="utf-8")
    return await db.ingest_csv_to_db(str(path), client_id, original_filename=name)


# ---- MRR (FIN-01) ----------------------------------------------------

@pytest.mark.asyncio
async def test_mrr_unavailable_when_no_recurring_flag_ever_provided(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-TEST", [f"{_this_month_date()},Sales,1000,Row,"])
    summary = await db.get_mrr_summary("CLI-TEST")
    assert summary["mrr_available"] is False
    assert summary["mrr"] is None


@pytest.mark.asyncio
async def test_mrr_computed_only_from_flagged_positive_current_month_rows(tmp_path, isolated_db):
    db = isolated_db
    this_month = _this_month_date(5)
    rows = [
        f"{this_month},Subs,500,Recurring revenue,true",     # counted
        f"{this_month},Subs,-100,Recurring refund,true",     # excluded: negative amount
        f"{this_month},OneOff,9999,Big one-time sale,false", # excluded: not recurring
        f"{this_month},Subs,50,Unflagged row,",               # excluded: unflagged (NULL)
    ]
    await _ingest(db, tmp_path, "CLI-TEST", rows)
    summary = await db.get_mrr_summary("CLI-TEST")
    assert summary["mrr_available"] is True
    assert summary["mrr"] == pytest.approx(500.0)
    assert summary["recurring_flagged_row_count"] == 2  # the two rows explicitly flagged true (500 and -100)


@pytest.mark.asyncio
async def test_mrr_zero_is_a_real_answer_not_unavailable(tmp_path, isolated_db):
    db = isolated_db
    this_month = _this_month_date(5)
    # Flagged, but false -- MRR should be a real $0.00, not "unavailable".
    await _ingest(db, tmp_path, "CLI-TEST", [f"{this_month},Sales,1000,Row,false"])
    summary = await db.get_mrr_summary("CLI-TEST")
    assert summary["mrr_available"] is True
    assert summary["mrr"] == 0.0


# ---- Ledger row drill-down (DIFF-01) ----------------------------------

@pytest.mark.asyncio
async def test_ledger_rows_have_stable_distinct_row_ids(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-TEST", [
        "2026-01-01,Sales,100,Row 1,",
        "2026-01-02,Sales,200,Row 2,",
        "2026-01-03,Sales,300,Row 3,",
    ])
    result = await db.get_ledger_rows("CLI-TEST")
    row_ids = [r["row_id"] for r in result["rows"]]
    assert len(row_ids) == 3
    assert all(rid is not None for rid in row_ids)
    assert len(set(row_ids)) == 3  # all distinct
    assert result["legacy_row_count"] == 0


@pytest.mark.asyncio
async def test_ledger_rows_category_and_month_filters(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-TEST", [
        "2026-01-15,Sales,100,Jan Sales,",
        "2026-02-15,Sales,200,Feb Sales,",
        "2026-01-15,Rent,-50,Jan Rent,",
    ])
    by_category = await db.get_ledger_rows("CLI-TEST", category="Rent")
    assert by_category["row_count"] == 1
    assert by_category["rows"][0]["description"] == "Jan Rent"

    by_month = await db.get_ledger_rows("CLI-TEST", month="2026-01")
    assert by_month["row_count"] == 2


# ---- Category suggestions (DIFF-06) -----------------------------------

@pytest.mark.asyncio
async def test_category_suggestion_from_matching_keywords(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-TEST", [
        "2026-01-01,Software,50,Adobe Creative Cloud subscription,",
        "2026-01-02,Software,60,Adobe Photoshop license,",
        "2026-01-03,Uncategorized,55,Adobe Illustrator renewal,",
    ])
    result = await db.suggest_category_fixes("CLI-TEST")
    assert len(result["suggestions"]) == 1
    suggestion = result["suggestions"][0]
    assert suggestion["suggested_category"] == "Software"
    assert suggestion["matched_row_count"] == 2
    assert suggestion["confidence"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_category_suggestion_none_when_no_keyword_overlap(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-TEST", [
        "2026-01-01,Software,50,Adobe Creative Cloud,",
        "2026-01-02,Uncategorized,60,Completely unrelated widget purchase,",
    ])
    result = await db.suggest_category_fixes("CLI-TEST")
    assert result["suggestions"] == []


@pytest.mark.asyncio
async def test_apply_category_suggestion_updates_exact_row(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-TEST", ["2026-01-01,Uncategorized,50,Row,"])
    rows = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    row_id = rows[0]["row_id"]

    updated = await db.apply_category_suggestion("CLI-TEST", row_id, "Software")
    assert updated is True

    rows_after = (await db.get_ledger_rows("CLI-TEST"))["rows"]
    assert rows_after[0]["category"] == "Software"


@pytest.mark.asyncio
async def test_apply_category_suggestion_wrong_tenant_is_noop(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-A", ["2026-01-01,Uncategorized,50,Row,"])
    row_id = (await db.get_ledger_rows("CLI-A"))["rows"][0]["row_id"]

    # A different tenant guessing/reusing that row_id must not be able to
    # touch CLI-A's row.
    updated = await db.apply_category_suggestion("CLI-B", row_id, "Software")
    assert updated is False
    rows_a = (await db.get_ledger_rows("CLI-A"))["rows"]
    assert rows_a[0]["category"] == "Uncategorized"  # untouched


@pytest.mark.asyncio
async def test_apply_category_suggestion_missing_row_id_raises(isolated_db):
    db = isolated_db
    with pytest.raises(ValueError):
        await db.apply_category_suggestion("CLI-TEST", None, "Software")


# ---- Ingestion history (DATA-08) / deletion (DATA-09) ------------------

@pytest.mark.asyncio
async def test_ingestion_history_records_success_and_rejection(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-TEST", ["2026-01-01,Sales,100,Row,"], name="good.csv")

    bad_path = tmp_path / "bad.csv"
    bad_path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        await db.ingest_csv_to_db(str(bad_path), "CLI-TEST", original_filename="bad.csv")

    history = await db.get_ingestion_history("CLI-TEST")
    statuses = {h["filename"]: h["status"] for h in history}
    assert statuses["good.csv"] == "SUCCESS"
    assert statuses["bad.csv"] == "REJECTED"


@pytest.mark.asyncio
async def test_delete_tenant_ledger_removes_only_that_tenant(tmp_path, isolated_db):
    db = isolated_db
    await _ingest(db, tmp_path, "CLI-A", ["2026-01-01,Sales,100,Row A,"], name="a.csv")
    await _ingest(db, tmp_path, "CLI-B", ["2026-01-01,Sales,200,Row B,"], name="b.csv")

    deleted = await db.delete_tenant_ledger("CLI-A")
    assert deleted == 1

    assert (await db.get_ledger_chart_context("CLI-A"))["row_count"] == 0
    assert (await db.get_ledger_chart_context("CLI-B"))["row_count"] == 1


# ---- Forecast accuracy (FIN-04) ---------------------------------------

@pytest.mark.asyncio
async def test_forecast_accuracy_no_snapshots_yet(isolated_db):
    db = isolated_db
    result = await db.get_forecast_accuracy("CLI-TEST")
    assert result["evaluated"] == []
    assert result["pending"] == []


@pytest.mark.asyncio
async def test_forecast_accuracy_evaluates_past_month_against_real_actuals(tmp_path, isolated_db):
    db = isolated_db
    last_month = (date.today().replace(day=1) - timedelta(days=1))
    last_month_key = last_month.strftime("%Y-%m")

    await _ingest(db, tmp_path, "CLI-TEST", [f"{last_month.isoformat()},Sales,1000,Row,"])
    # NOTE: log_forecast_snapshot_sync is deliberately a no-op when called
    # from inside an already-running event loop (see
    # test_log_forecast_snapshot_sync_noop_inside_running_loop below) --
    # a pytest-asyncio test IS a running loop, so this test calls the real
    # async log_forecast_snapshot(...) directly instead. Note the field is
    # `months_ahead`, not `month`: target_month is computed internally as
    # _add_months(last_historical_period, months_ahead).
    await db.log_forecast_snapshot(
        "CLI-TEST",
        last_historical_period=last_month_key,
        method="linear",
        r_squared=0.9,
        forecast_by_month=[{"months_ahead": 0, "projected_revenue": 900.0, "ci_lower_95": 800.0, "ci_upper_95": 1000.0}],
    )

    result = await db.get_forecast_accuracy("CLI-TEST")
    assert len(result["evaluated"]) == 1
    evaluated = result["evaluated"][0]
    assert evaluated["target_month"] == last_month_key
    assert evaluated["actual_revenue"] == pytest.approx(1000.0)
    assert evaluated["within_95pct_interval"] is True


@pytest.mark.asyncio
async def test_forecast_accuracy_future_month_is_pending(isolated_db):
    db = isolated_db
    current_key = date.today().strftime("%Y-%m")
    # 12 months ahead of "now" is guaranteed still in the future regardless
    # of what today's actual date is when this suite runs.
    future = db._add_months(current_key, 12)
    await db.log_forecast_snapshot(
        "CLI-TEST",
        last_historical_period=current_key,
        method="linear",
        r_squared=0.9,
        forecast_by_month=[{"months_ahead": 12, "projected_revenue": 5000.0, "ci_lower_95": 4000.0, "ci_upper_95": 6000.0}],
    )
    result = await db.get_forecast_accuracy("CLI-TEST")
    assert len(result["pending"]) == 1
    assert result["pending"][0]["target_month"] == future


@pytest.mark.asyncio
async def test_log_forecast_snapshot_sync_noop_inside_running_loop(isolated_db):
    """
    log_forecast_snapshot_sync explicitly refuses to run (logs a warning,
    returns without raising) when called from inside a loop that's already
    running -- calling it from an `async def` test IS that situation. This
    pins down that documented behavior: no exception, and genuinely no row
    written (not a silent partial write).
    """
    db = isolated_db
    db.log_forecast_snapshot_sync(
        "CLI-TEST", last_historical_period="2026-01", method="linear",
        r_squared=0.9, forecast_by_month=[{"months_ahead": 1, "projected_revenue": 100.0, "ci_lower_95": 50.0, "ci_upper_95": 150.0}],
    )
    result = await db.get_forecast_accuracy("CLI-TEST")
    assert result["evaluated"] == []
    assert result["pending"] == []


# ---- _suggest_category_for (pure function, no DB) ----------------------

def test_suggest_category_for_pure_function(isolated_db):
    db = isolated_db
    categorized = [
        ("Adobe Creative Cloud subscription", "Software"),
        ("Adobe Photoshop license", "Software"),
        ("Uber ride to airport", "Travel"),
    ]
    result = db._suggest_category_for("Adobe Illustrator renewal", categorized)
    assert result["suggested_category"] == "Software"
    assert result["matched_row_count"] == 2

    result_none = db._suggest_category_for("Completely unrelated text", categorized)
    assert result_none["suggested_category"] is None
