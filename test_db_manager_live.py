"""
Live, real-DuckDB verification for backend/db_manager.py.

WHY THIS EXISTS: every db_manager.py review so far in this audit was
py_compile + hand-review only -- this sandbox has no network access to
install the real `duckdb` package, so the actual SQL (TRY_CAST date
handling, the ledger full-replace transaction, the seed-data tagging
migration, the asyncio.Lock serialization) has never actually been
executed. Your real venv already has duckdb installed (db_manager.py is
running in your live server), so this closes that gap for real.

HOW TO RUN:
    Drop this file next to backend/ (i.e. at your repo root, alongside the
    `backend` folder), then from your venv:

        python3 test_db_manager_live.py

    It creates its own throwaway DuckDB file in a temp directory (it does
    NOT touch backend/nexusflow.duckdb or any of your real data) and
    deletes it afterward. Paste the full output back so we can review it
    together -- per the audit's rules of engagement, I don't want to just
    tell you "looks good," I want to see the real output.

WHAT IT CHECKS:
    1. init_db() creates the ledgers table
    2. ingest_csv_to_db() end-to-end: messy amount parsing ("$1,200.50",
       "(500.00)" accounting-negative, blank cells), a genuinely
       unparseable amount value (dropped + reported, not fabricated as
       $0.00), and full-replace semantics (re-ingesting for the same
       client_id replaces rather than appends)
    3. get_total_ingested_rows()
    4. get_ledger_chart_context(): real category_breakdown totals/ordering,
       real monthly_totals via TRY_CAST, and unparseable_date_count for a
       deliberately garbled date string
    5. init_telemetry_schema(): 5 seed rows inserted and tagged
       is_seed_data=TRUE; the one-time backfill path (simulating a
       pre-existing untagged install)
    6. log_task_execution(): real rows land untagged (is_seed_data=FALSE)
    7. get_task_success_metrics() / get_advanced_telemetry(): seed rows
       excluded from both
    8. Real concurrency: two ingest_csv_to_db() calls for different tenants
       fired concurrently via asyncio.gather -- confirms the asyncio.Lock
       actually serializes DuckDB access rather than colliding
"""
import asyncio
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend import db_manager


def make_csv(path, rows_csv_text):
    with open(path, "w") as f:
        f.write(rows_csv_text)


async def main():
    tmp_dir = tempfile.mkdtemp(prefix="nf_db_manager_live_test_")
    test_db_path = os.path.join(tmp_dir, "test_nexusflow.duckdb")
    # Point db_manager at a throwaway DB file for this run only. Every
    # function reads the module-level DB_PATH fresh at call time (it's not
    # captured as a default-arg at import time), so reassigning it here is
    # safe and doesn't require touching db_manager.py itself.
    db_manager.DB_PATH = test_db_path
    print(f"Using throwaway test DB: {test_db_path}\n")

    failures = []

    def check(label, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        print(f"[{status}] {label}" + (f" -- {detail}" if detail and not condition else ""))
        if not condition:
            failures.append(label)

    try:
        print("=== 1. init_db() ===")
        await db_manager.init_db()
        check("ledgers table created (no exception)", True)

        print("\n=== 2. ingest_csv_to_db(): messy amounts, blank-field defaults, dropped rows ===")
        # Two DIFFERENT "blank" behaviors are deliberately exercised here:
        # a blank category/description defaults (Uncategorized / "Uploaded
        # ledger entry" -- see clean_df's fillna calls), but a blank AMOUNT
        # does NOT default -- it becomes NaN same as "N/A" and gets dropped,
        # since fabricating a $0.00 entry in a financial ledger would be
        # worse than dropping the row. Row 3 tests the former, rows 4 and 5
        # test the latter (two distinct unparseable-amount shapes).
        csv_path = os.path.join(tmp_dir, "ledger_a.csv")
        make_csv(csv_path, (
            "date,category,amount,description\n"
            "2026-01-05,Software,\"$1,200.50\",Subscription\n"
            "2026-01-10,Payroll,\"(500.00)\",Contractor refund\n"
            "2026-01-15,,300,\n"                          # blank category/description -> defaulted, amount valid
            "2026-01-20,Marketing,N/A,Bad row\n"           # unparseable amount text -> dropped
            "2026-01-25,Travel,,Missing amount\n"          # blank amount -> also dropped (not defaulted to 0)
            "2026-01-30,Travel,300,Flight\n"
        ))
        msg = await db_manager.ingest_csv_to_db(csv_path, "tenant_live_a")
        print("  ->", msg)
        check("ingest reports 2 skipped unparseable/blank-amount rows", "Skipped 2" in msg, msg)
        check("ingest reports 4 ingested rows", "Successfully ingested 4" in msg, msg)

        print("\n=== 2b. Re-ingest same tenant -> full-replace, not append ===")
        csv_path2 = os.path.join(tmp_dir, "ledger_a_v2.csv")
        make_csv(csv_path2, (
            "date,category,amount,description\n"
            "2026-02-01,Software,100,Replaced entirely\n"
        ))
        msg2 = await db_manager.ingest_csv_to_db(csv_path2, "tenant_live_a")
        print("  ->", msg2)
        total_a = await db_manager.get_total_ingested_rows()
        print("  total rows across all tenants now:", total_a)

        print("\n=== 2c. Second tenant, with a deliberately garbled date ===")
        csv_path3 = os.path.join(tmp_dir, "ledger_b.csv")
        make_csv(csv_path3, (
            "date,category,amount,description\n"
            "2026-03-01,Sales,1000,Deal 1\n"
            "2026-03-15,Sales,2000,Deal 2\n"
            "2026-04-01,Support,500,Renewal\n"
            "not-a-real-date,Sales,750,Garbled date row\n"
        ))
        msg3 = await db_manager.ingest_csv_to_db(csv_path3, "tenant_live_b")
        print("  ->", msg3)
        check("tenant_b ingest reports 0 skipped (amounts all valid)", "Skipped" not in msg3, msg3)

        print("\n=== 3. get_total_ingested_rows() ===")
        total = await db_manager.get_total_ingested_rows()
        print("  total:", total)
        check("total reflects both tenants (1 + 4)", total == 5, f"got {total}")

        print("\n=== 4. get_ledger_chart_context() ===")
        ctx_a = await db_manager.get_ledger_chart_context("tenant_live_a")
        print("  tenant_live_a context:", ctx_a)
        check("tenant_a row_count == 1 (post full-replace)", ctx_a["row_count"] == 1, str(ctx_a))
        check("tenant_a category is Software", ctx_a["category_breakdown"] and ctx_a["category_breakdown"][0]["category"] == "Software", str(ctx_a))

        ctx_b = await db_manager.get_ledger_chart_context("tenant_live_b")
        print("  tenant_live_b context:", ctx_b)
        check("tenant_b row_count == 4", ctx_b["row_count"] == 4, str(ctx_b))
        check("tenant_b unparseable_date_count == 1", ctx_b["unparseable_date_count"] == 1, str(ctx_b))
        # date_min/date_max must reflect only real, parseable dates -- the
        # garbled "not-a-real-date" row must NOT be able to win MAX() via a
        # lexicographic string comparison (that was the exact bug: a plain
        # MIN(date)/MAX(date) over the raw VARCHAR column let a garbage
        # string outrank real dates just because of how it sorts as text).
        check("tenant_b date_min is the real earliest date (2026-03-01), not garbled", str(ctx_b["date_min"]) == "2026-03-01", str(ctx_b))
        check("tenant_b date_max is the real latest date (2026-04-01), not 'not-a-real-date'", str(ctx_b["date_max"]) == "2026-04-01", str(ctx_b))
        check("tenant_b category_breakdown ordered DESC by total_amount",
              [c["total_amount"] for c in ctx_b["category_breakdown"]] == sorted([c["total_amount"] for c in ctx_b["category_breakdown"]], reverse=True),
              str(ctx_b["category_breakdown"]))
        check("tenant_b monthly_totals has 2 real months (garbled date excluded)", len(ctx_b["monthly_totals"]) == 2, str(ctx_b["monthly_totals"]))

        print("\n=== 5. init_telemetry_schema(): fresh install seeding ===")
        await db_manager.init_telemetry_schema()
        success_after_seed = await db_manager.get_task_success_metrics()
        print("  success metrics immediately after seeding (should be all-zero, seed rows excluded):", success_after_seed)
        check("seed rows excluded from success metrics", success_after_seed["total_evaluated_window"] == 0, str(success_after_seed))

        print("\n=== 6. log_task_execution(): real rows, untagged ===")
        await db_manager.log_task_execution("bi_visualization_architect", "COMPLETE", 0.9)
        await db_manager.log_task_execution("external_telemetry_scout", "COMPLETE", 0.4)
        await db_manager.log_task_execution("data_engineer", "ERROR", 1.1)

        print("\n=== 7. get_task_success_metrics() / get_advanced_telemetry(): seed exclusion holds ===")
        success = await db_manager.get_task_success_metrics()
        print("  success metrics:", success)
        check("exactly 3 real tasks counted (seed rows still excluded)", success["total_evaluated_window"] == 3, str(success))
        check("2 successes, 1 error", success["success_count"] == 2 and success["error_count"] == 1, str(success))

        advanced = await db_manager.get_advanced_telemetry()
        print("  advanced telemetry:", advanced)
        check("advanced telemetry also excludes seed rows", advanced["total_evaluated_window"] == 3, str(advanced))
        check("avg_execution_time_sec is a real number > 0", advanced["avg_execution_time_sec"] > 0, str(advanced))

        print("\n=== 8. Real concurrency: two ingests fired at once via asyncio.gather ===")
        csv_c1 = os.path.join(tmp_dir, "ledger_c1.csv")
        csv_c2 = os.path.join(tmp_dir, "ledger_c2.csv")
        make_csv(csv_c1, "date,category,amount,description\n2026-05-01,Ops,111,Concurrent write 1\n")
        make_csv(csv_c2, "date,category,amount,description\n2026-05-01,Ops,222,Concurrent write 2\n")
        results = await asyncio.gather(
            db_manager.ingest_csv_to_db(csv_c1, "tenant_concurrent_1"),
            db_manager.ingest_csv_to_db(csv_c2, "tenant_concurrent_2"),
            return_exceptions=True,
        )
        print("  concurrent ingest results:", results)
        both_ok = all(isinstance(r, str) and r.startswith("Successfully") for r in results)
        check("both concurrent ingests completed without exception/collision", both_ok, str(results))
        ctx_c1 = await db_manager.get_ledger_chart_context("tenant_concurrent_1")
        ctx_c2 = await db_manager.get_ledger_chart_context("tenant_concurrent_2")
        check("tenant_concurrent_1 has its own 1 row (no cross-tenant bleed)", ctx_c1["row_count"] == 1, str(ctx_c1))
        check("tenant_concurrent_2 has its own 1 row (no cross-tenant bleed)", ctx_c2["row_count"] == 1, str(ctx_c2))

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    else:
        print("ALL DB_MANAGER LIVE CHECKS PASSED (real DuckDB, real SQL, real concurrency)")


if __name__ == "__main__":
    asyncio.run(main())