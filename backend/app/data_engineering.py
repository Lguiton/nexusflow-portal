import io
import re
import logging
import pandas as pd
import duckdb
from typing import Dict, Any, List, Tuple

logger = logging.getLogger("NexusFlow-DataEngineering")

class DataEngineerAgent:
    """
    Agent #3: The Pipeline Mechanic
    Self-healing schema repair, null value imputation, and header sanitization.
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


class DWAAgent:
    """
    Agent #5: The Data Warehouse Administrator Architect
    Enforces Row-Level Security (RLS) tenant isolation and columnar readiness.
    """
    def enforce_rls_and_transform(self, df: pd.DataFrame, tenant_id: str) -> pd.DataFrame:
        df['tenant_id'] = tenant_id
        logger.info(f"DWA Agent (#5) successfully assigned RLS tenant key '{tenant_id}' across {len(df)} records.")
        return df


class BigDataAnalystAgent:
    """
    Agent #6: The Cluster Engine (DuckDB)
    High-speed in-memory columnar query aggregations for analytical workloads.
    """
    def execute_duckdb_analytics(self, df: pd.DataFrame) -> Dict[str, Any]:
        con = duckdb.connect(database=':memory:')
        con.register('df_raw', df)
        
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
        if 'tenant_id' in numeric_cols:
            numeric_cols.remove('tenant_id')

        query_results = {}
        if numeric_cols:
            primary_col = numeric_cols[0]
            agg_query = f"""
                SELECT 
                    COUNT(*) as total_records,
                    ROUND(AVG({primary_col}), 2) as avg_{primary_col},
                    ROUND(SUM({primary_col}), 2) as sum_{primary_col},
                    ROUND(MIN({primary_col}), 2) as min_{primary_col},
                    ROUND(MAX({primary_col}), 2) as max_{primary_col}
                FROM df_raw
            """
            res = con.execute(agg_query).df()
            query_results = res.to_dict(orient='records')[0]
        else:
            query_results = {"total_records": len(df), "note": "No numerical features detected for aggregation."}

        con.close()
        return query_results


class DBAAgent:
    """
    Agent #4: The DBA Mechanic
    Dynamically generates SQL DDL schemas and index layouts for persistent warehousing.
    """
    def generate_sql_schema(self, df: pd.DataFrame, table_name: str) -> str:
        con = duckdb.connect(database=':memory:')
        con.register('temp_df', df)
        
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

        con.close()
        
        ddl_script = f"CREATE TABLE IF NOT EXISTS {table_name} (\n" + ",\n".join(col_definitions) + "\n);\n"
        ddl_script += f"CREATE INDEX IF NOT EXISTS idx_{table_name}_tenant ON {table_name} (tenant_id);"
        return ddl_script


# Global Agent Instances
data_engineer = DataEngineerAgent()
dwa_agent = DWAAgent()
big_data_analyst = BigDataAnalystAgent()
dba_agent = DBAAgent()