import logging
import pandas as pd
from pathlib import Path
from backend.db_manager import ingest_csv_to_db

logger = logging.getLogger("eivanta.pipeline.etl")

class EnterpriseETLPipeline:
    """
    Core ETL Pipeline module supporting Agent #03 (Data Engineer).
    Handles batch ingestion, tenant scoping, and columnar database storage.
    """
    def process_and_load_ledger(self, file_path: str, client_id: str) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"ETL source path not found: {file_path}")

        if not client_id or not client_id.strip():
            raise ValueError("ETL Security Error: Missing client_id for multi-tenant isolation.")

        logger.info("Executing ETL pipeline for tenant %s from source %s", client_id, file_path)
        
        # Delegates secure ingestion to DuckDB manager
        result_status = ingest_csv_to_db(str(path), client_id=client_id, table_name="ledgers")
        return result_status
