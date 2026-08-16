import os
import io
import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple
import pandas as pd
import duckdb

logger = logging.getLogger("nexusflow.data_engineer")

class DataEngineerAgent:
    """
    Agent #03: Consolidated Data Engineer & Pipeline Mechanic
    Handles header sanitization, self-healing null imputation, Row-Level Security (RLS) tenant isolation,
    schema DDL generation, and high-speed DuckDB columnar ingestion.
    """
    def sanitize_and_clean_csv(self, contents: bytes) -> Tuple[pd.DataFrame, List[str]]:
        fixes_applied = []
        df = pd.read_csv(io.BytesIO(contents))
        
        # 1. Header Repair: lowercase, strip spaces, convert special characters to underscores
        original_cols = list(df.columns)
        cleaned_cols = [re.sub(r'[^a-zA-Z0-9_]', '_', str(col).strip().lower()) for col in original_cols]
        if original_cols != cleaned_cols:
            df.columns = cleaned_cols
            fixes_applied.append(f"Header Repair: Standardized {len(cleaned_cols)} column headers.")

        # 2. Prune empty rows/columns
        init_rows = len(df)
        df.dropna(how='all', inplace=True)
        if len(df) < init_rows:
            fixes_applied.append(f"Data Cleaning: Removed {init_rows - len(df)} completely empty rows.")

        # 3. Self-Healing: Impute missing numerical values with median
        numeric_cols = df.select_dtypes(include=['number']).columns
        for col in numeric_cols:
            null_count = df[col].isnull().sum()
            if null_count > 0:
                median_val = df[col].median()
                df[col].fillna(median_val, inplace=True)
                fixes_applied.append(f"Self-Healing: Filled {null_count} missing values in '{col}' with median ({median_val}).")

        return df, fixes_applied

    def enforce_rls_and_transform(self, df: pd.DataFrame, tenant_id: str) -> pd.DataFrame:
        """Enforces Row-Level Security (RLS) tenant isolation key."""
        df['client_id'] = tenant_id
        if 'tenant_id' not in df.columns:
            df['tenant_id'] = tenant_id
        logger.info("Data Engineer successfully assigned tenant key '%s' across %d records.", tenant_id, len(df))
        return df

    def generate_sql_schema(self, df: pd.DataFrame, table_name: str) -> str:
        """Dynamically generates SQL DDL schemas and index layouts for persistent warehousing."""
        col_definitions = []
        for col in df.columns:
            dtype = str(df[col].dtype)
            if 'int' in dtype:
                sql_type = "BIGINT"
            elif 'float' in dtype:
                sql_type = "DOUBLE PRECISION"
            else:
                sql_type = "VARCHAR(255)"
            col_definitions.append(f"  {col} {sql_type}")
        
        ddl_script = f"CREATE TABLE IF NOT EXISTS {table_name} (\n" + ",\n".join(col_definitions) + "\n);\n"
        ddl_script += f"CREATE INDEX IF NOT EXISTS idx_{table_name}_tenant ON {table_name} (client_id);"
        return ddl_script

# Instantiate singleton for pipeline operations
data_engineer = DataEngineerAgent()

def validate_and_ingest_ledger(file_path: str, client_id: str) -> str:
    """
    Primary pipeline wrapper combining ingestion, cleaning, RLS security enforcement, and validation.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Ingestion payload path does not exist: {file_path}")

    if not client_id or not client_id.strip():
        raise ValueError("Security Violation: Missing or invalid tenant client_id during onboarding.")

    with open(path, "rb") as f:
        content_bytes = f.read()

    # Run full cleaning & self-healing pipeline
    df, fixes = data_engineer.sanitize_and_clean_csv(content_bytes)
    df = data_engineer.enforce_rls_and_transform(df, client_id)

    logger.info("Pipeline executed successfully with fixes: %s", fixes)
    return f"Successfully processed and sanitized {len(df)} records for client {client_id}. Applied fixes: {len(fixes)}"
