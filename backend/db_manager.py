import duckdb
import pandas as pd
import os
import re
import csv
from difflib import get_close_matches

DB_PATH = "db/nexusflow.duckdb"

# Canonical schema: maps a stable internal column name to the various
# header spellings different clients' exports might use. Extend this
# as you encounter new variants in the wild.
COLUMN_ALIASES = {
    "id": ["id", "transaction_id", "txn_id", "tx_id", "record_id", "order_id", "order_num"],
    "client_name": ["client_name", "client", "customer", "customer_name", "account_name"],
    "mrr": ["mrr", "monthly_recurring_revenue", "revenue", "amount", "total"],
    "category": ["category", "type", "expense_category", "tag"],
}


def _validate_csv_structure(csv_file_path: str) -> None:
    """
    Rejects CSVs with an inconsistent number of fields per row -- the
    classic signature of two exports accidentally concatenated into one
    file (a second header row embedded mid-file). Without this check,
    pandas silently pads short rows with NaN in the trailing columns,
    which produces a column-shift bug that looks like corrupted data
    rather than a malformed file.
    """
    with open(csv_file_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            raise ValueError("CSV file appears to be empty.")
        expected_fields = len(header)

        for line_num, row in enumerate(reader, start=2):
            if not row:
                continue  # skip blank lines
            if row == header:
                raise ValueError(
                    f"Line {line_num} repeats the header row "
                    f"('{','.join(row)}'). This file looks like two exports "
                    f"concatenated together -- please upload each export as "
                    f"a separate file."
                )
            if len(row) != expected_fields:
                raise ValueError(
                    f"Line {line_num} has {len(row)} fields but the header "
                    f"has {expected_fields}. This usually means two files "
                    f"got merged into one, or a row is truncated. "
                    f"Line content: {','.join(row)}"
                )


def get_connection(read_only: bool = False):
    os.makedirs("db", exist_ok=True)
    return duckdb.connect(DB_PATH, read_only=read_only)


def _normalize_header(col: str) -> str:
    """Lowercase, strip, and collapse anything non-alphanumeric to underscores
    so 'Transaction ID', 'transaction-id', and 'TRANSACTION_ID' all match."""
    return re.sub(r"[^a-z0-9]", "_", str(col).strip().lower()).strip("_")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Maps incoming CSV headers onto the canonical schema regardless of the
    exact wording a client used. Columns that don't match any known alias
    (even fuzzily) are kept, not dropped -- prefixed with 'unmapped_' so
    they don't collide with canonical names and no data silently disappears.
    """
    alias_lookup = {}
    for canonical, variants in COLUMN_ALIASES.items():
        for v in variants:
            alias_lookup[_normalize_header(v)] = canonical

    rename_map = {}
    seen_canonical = set()
    for original_col in df.columns:
        norm = _normalize_header(original_col)

        canonical = alias_lookup.get(norm)
        if canonical is None:
            close = get_close_matches(norm, alias_lookup.keys(), n=1, cutoff=0.8)
            canonical = alias_lookup[close[0]] if close else None

        if canonical and canonical not in seen_canonical:
            rename_map[original_col] = canonical
            seen_canonical.add(canonical)
        else:
            rename_map[original_col] = f"unmapped_{norm}"

    return df.rename(columns=rename_map)


def ingest_csv_to_db(csv_file_path: str, client_id: str, table_name: str = "ledgers", mode: str = "append") -> str:
    """
    client_id: the tenant this upload belongs to. Stamped onto every row so
        rows from different clients live in the same physical table but can
        never be queried across each other by accident.
    mode="append" (default): adds rows to an existing table, matching
        columns BY NAME. If the CSV introduces a new canonical column,
        the table schema evolves to include it. Missing columns on either
        side are filled with NULL -- values never shift into the wrong
        column just because column order or count differs between uploads.
    mode="replace": wipes and rebuilds the table from this file alone.
        Use only when you explicitly want to discard prior data. NOTE: this
        only clears this client_id's own rows, never other tenants' data.
    """
    if not client_id or not str(client_id).strip():
        raise ValueError("client_id is required for ingestion.")

    _validate_csv_structure(csv_file_path)

    con = get_connection(read_only=False)
    try:
        # Atomic Transaction Isolation
        con.execute("BEGIN TRANSACTION;")

        df = pd.read_csv(csv_file_path)
        if df.empty:
            con.execute("COMMIT;")
            return "No rows found in the uploaded file -- nothing was ingested."

        df = normalize_columns(df)
        df["client_id"] = str(client_id)

        table_exists = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [table_name],
        ).fetchone()[0] > 0

        if not table_exists:
            con.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM df')
            con.execute("COMMIT;")
            return f"Created '{table_name}' fresh with {len(df)} rows and {len(df.columns)} columns."

        existing_cols = [
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                [table_name],
            ).fetchall()
        ]

        new_cols = [c for c in df.columns if c not in existing_cols]
        for col in new_cols:
            con.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" VARCHAR')

        if mode == "replace":
            # Only this tenant's rows are cleared -- other clients' data in
            # the same physical table is untouched.
            con.execute(f'DELETE FROM "{table_name}" WHERE client_id = ?', [str(client_id)])

        # DuckDB's BY NAME insert matches source and destination columns by
        # name and fills anything missing on either side with NULL.
        con.execute(f'INSERT INTO "{table_name}" BY NAME SELECT * FROM df')

        con.execute("COMMIT;")
        verb = "Replaced" if mode == "replace" else "Appended"
        return f"{verb} {len(df)} rows in '{table_name}' for client '{client_id}' ({len(new_cols)} new column(s) added)."
    except Exception as e:
        con.execute("ROLLBACK;")
        raise RuntimeError(f"Database transaction rollback triggered: {str(e)}")
    finally:
        con.close()


def query_db(sql_query: str, params: list = None):
    con = get_connection(read_only=True)
    try:
        return con.execute(sql_query, params or []).df()
    finally:
        con.close()


# Columns the LLM is allowed to reference when building a query intent.
QUERYABLE_COLUMNS = {"id", "client_name", "mrr", "category"}
ALLOWED_OPERATORS = {"=", "!=", ">", "<", ">=", "<="}
ALLOWED_AGGREGATES = {"sum", "count", "avg", "min", "max"}


def build_safe_query(intent: dict, client_id: str):
    """
    Turns a structured intent into a parameterized query with server-side tenant isolation.
    """
    if not client_id or not str(client_id).strip():
        raise ValueError("client_id is required for querying.")

    params: list = [str(client_id)]
    where_clauses = ["client_id = ?"]

    for f in (intent.get("filters") or [])[:10]:  # cap filter count
        col, op, val = f.get("column"), f.get("op"), f.get("value")
        if col not in QUERYABLE_COLUMNS or op not in ALLOWED_OPERATORS:
            continue
        where_clauses.append(f'"{col}" {op} ?')
        params.append(val)

    where_sql = " AND ".join(where_clauses)

    if intent.get("operation") == "aggregate":
        func = intent.get("aggregate_function")
        col = intent.get("aggregate_column")
        if func not in ALLOWED_AGGREGATES:
            raise ValueError(f"Unsupported aggregate function: {func!r}")
        if func == "count":
            select_sql = "COUNT(*) AS result"
        else:
            if col not in QUERYABLE_COLUMNS:
                raise ValueError(f"Unsupported aggregate column: {col!r}")
            select_sql = f'{func.upper()}("{col}") AS result'
        sql = f'SELECT {select_sql} FROM ledgers WHERE {where_sql}'
        return sql, params

    # default: list rows
    sql = f'SELECT id, client_name, mrr, category FROM ledgers WHERE {where_sql}'

    order_col = intent.get("order_by")
    if order_col in QUERYABLE_COLUMNS:
        order_dir = "DESC" if intent.get("order_dir") == "DESC" else "ASC"
        sql += f' ORDER BY "{order_col}" {order_dir}'

    limit = intent.get("limit")
    limit = limit if isinstance(limit, int) and 0 < limit <= 500 else 100
    sql += f" LIMIT {limit}"

    return sql, params
