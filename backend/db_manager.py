import os
import duckdb
import pandas as pd
import logging

logger = logging.getLogger("nexusflow.db_manager")

# FIX: DB_PATH was a bare relative filename, meaning the actual database
# file location silently depended on whatever directory uvicorn happened
# to be launched from — a likely contributor to prior "wrong data" / path
# confusion bugs (see the WSL/Windows path issues in the debugging log).
# Resolving it relative to this file's own location makes it deterministic
# regardless of the working directory the app is started from.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nexusflow.duckdb")

def init_db():
    conn = duckdb.connect(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ledgers (
                client_id VARCHAR,
                date VARCHAR,
                category VARCHAR,
                amount DOUBLE,
                description VARCHAR
            )
        """)
    finally:
        conn.close()

def ingest_csv_to_db(file_path: str, client_id: str) -> str:
    init_db()

    if not client_id:
        raise ValueError("client_id is required for tenant-isolated ingestion.")

    df = pd.read_csv(file_path)
    # Normalize column names to lowercase
    df.columns = [c.strip().lower() for c in df.columns]

    # Map common CSV header variants to our standard schema
    # Expected: date, category, amount (or revenue/expense), description
    if 'amount' not in df.columns:
        if 'revenue' in df.columns and 'expense' in df.columns:
            df['amount'] = df['revenue'].fillna(0) - df['expense'].fillna(0)
        elif 'revenue' in df.columns:
            df['amount'] = df['revenue']
        elif 'cost' in df.columns or 'expense' in df.columns:
            df['amount'] = -abs(df['cost'] if 'cost' in df.columns else df['expense'])
        else:
            numeric_cols = df.select_dtypes(include=['number']).columns
            if len(numeric_cols) > 0:
                df['amount'] = df[numeric_cols[0]]
            else:
                raise ValueError("CSV must contain an 'amount', 'revenue', or numeric column.")

    if 'category' not in df.columns:
        df['category'] = 'Uncategorized'
    if 'date' not in df.columns:
        df['date'] = '2026-08-01'
    if 'description' not in df.columns:
        df['description'] = 'Uploaded ledger entry'

    clean_df = pd.DataFrame({
        'client_id': client_id,
        'date': df['date'].astype(str),
        'category': df['category'].astype(str),
        'amount': df['amount'].astype(float),
        'description': df['description'].astype(str)
    })

    conn = duckdb.connect(DB_PATH)
    try:
        # FIX: DELETE + INSERT previously ran as two independent statements
        # with no transaction wrapping. If the INSERT failed after the
        # DELETE succeeded, the client's entire ledger would be silently
        # wiped with nothing re-inserted. Now both run atomically — if the
        # INSERT fails, the DELETE is rolled back too.
        #
        # NOTE (behavior, not a bug fix): this still fully replaces the
        # client's ledger on every upload rather than appending with
        # MD5-based duplicate detection, despite duplicate-protection being
        # described in earlier project documentation. That's a real
        # discrepancy worth resolving deliberately, not something silently
        # changed here since it would alter ingestion behavior, not just
        # clean up a bug.
        conn.execute("BEGIN TRANSACTION")
        conn.execute("DELETE FROM ledgers WHERE client_id = ?", [client_id])
        conn.execute("INSERT INTO ledgers SELECT * FROM clean_df")
        conn.execute("COMMIT")
        row_count = conn.execute(
            "SELECT COUNT(*) FROM ledgers WHERE client_id = ?", [client_id]
        ).fetchone()[0]
        return f"Successfully ingested {row_count} records for tenant '{client_id}'."
    except Exception as e:
        conn.execute("ROLLBACK")
        logger.error(f"CSV Ingestion Failed for tenant '{client_id}': {e}")
        raise
    finally:
        # FIX: previously conn.close() was only reached on the success path;
        # an exception before it would leak the connection.
        conn.close()