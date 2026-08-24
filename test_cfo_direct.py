import json
import duckdb
import pandas as pd
from backend.db_manager import DB_PATH
from backend.agents.virtual_cfo import generate_cfo_briefing

# ------------------------------------------------------------------------
# FIXES APPLIED (verified against the real, current backend files via a
# live execution harness before delivery):
#
# 1. `db_path = "backend/nexus.db"` -- WRONG PATH. The real DuckDB file
#    this whole application actually reads and writes is
#    `db_manager.DB_PATH` (backend/nexusflow.duckdb). "backend/nexus.db"
#    is not that file -- on the real project disk it isn't even a .duckdb
#    file at all, it's a leftover DIRECTORY of the same name, so the
#    original script's `duckdb.connect(db_path, read_only=True)` could
#    never succeed; every run would silently fall straight into the
#    `except` branch and print a connection error, never actually
#    inspecting real data despite looking like it ran successfully. Fixed
#    to import the real DB_PATH directly from db_manager, so this script
#    can't go stale again if the path ever changes.
#
# 2. `generate_cfo_briefing` was imported but never called anywhere in the
#    original script -- despite the file being named test_cfo_direct.py,
#    it never actually exercised the CFO agent directly, only ran a raw
#    DuckDB schema/tenant diagnostic. Added a real call at the end so the
#    file does what its name says.
# ------------------------------------------------------------------------

print("--- NEXUSFLOW LEDGER DIAGNOSTIC TOOL ---")
print(f"Connecting to real DB_PATH: {DB_PATH}")

discovered_client_ids = []

try:
    conn = duckdb.connect(DB_PATH, read_only=True)

    # Check 1: Does the table exist and what are the columns?
    tables = conn.execute("SHOW TABLES").df()
    if 'ledgers' not in tables['name'].values:
        print("❌ ERROR: 'ledgers' table does not exist in the database.")
    else:
        print("✅ 'ledgers' table found.")
        columns = conn.execute("DESCRIBE ledgers").df()
        print("\n--- COLUMN SCHEMAS ---")
        print(columns[['column_name', 'column_type']])

        # Check 2: Show all client_ids currently holding data
        clients = conn.execute("SELECT DISTINCT client_id, COUNT(*) as rows FROM ledgers GROUP BY client_id").df()
        print("\n--- TENANTS WITH DATA ---")
        print(clients)
        discovered_client_ids = clients['client_id'].tolist()

        # Check 3: Check raw amounts
        raw_data = conn.execute("SELECT client_id, amount, category FROM ledgers LIMIT 5").df()
        print("\n--- FIRST 5 ROWS ---")
        print(raw_data)

    conn.close()

except Exception as e:
    print(f"Database connection error: {e}")

print("\n==================================================")
print("TESTING VIRTUAL CFO (Agent #06) - Direct Briefing")
print("==================================================")
cfo_test_client_id = discovered_client_ids[0] if discovered_client_ids else "CLI-001"
print(f"Generating live CFO briefing for tenant: {cfo_test_client_id}")
cfo_result = generate_cfo_briefing(client_id=cfo_test_client_id)
print(json.dumps(cfo_result, indent=2))

print("\n--- TESTS COMPLETE ---")
print(
    "\nNOTE: this file has no `def test_*` functions, so `pytest` will "
    "collect ZERO test items from it despite the test_ filename -- it is "
    "a manual diagnostic script meant to be read by eye, run directly with "
    "`python test_cfo_direct.py`, not `pytest test_cfo_direct.py`."
)
