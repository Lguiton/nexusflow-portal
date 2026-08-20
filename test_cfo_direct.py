import duckdb
import pandas as pd
from backend.agents.virtual_cfo import generate_cfo_briefing

db_path = "backend/nexus.db"

print("--- NIGERIAN PRINCE DIAGNOSTIC TOOL ---")

try:
    conn = duckdb.connect(db_path, read_only=True)
    
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
        
        # Check 3: Check raw amounts
        raw_data = conn.execute("SELECT client_id, amount, category FROM ledgers LIMIT 5").df()
        print("\n--- FIRST 5 ROWS ---")
        print(raw_data)

    conn.close()

except Exception as e:
    print(f"Database connection error: {e}")

