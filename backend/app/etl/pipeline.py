import pandas as pd
import io
import json
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

class OpsDataPipeline:
    def __init__(self, raw_bytes: bytes, filename: str):
        self.raw_bytes = raw_bytes
        self.filename = filename

    def extract_and_transform(self) -> pd.DataFrame:
        if self.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(self.raw_bytes))
        elif self.filename.endswith('.json'):
            df = pd.read_json(io.BytesIO(self.raw_bytes))
        else:
            raise ValueError("Unsupported file format. Expecting CSV or JSON.")

        df.columns = [col.strip().lower().replace(' ', '_') for col in df.columns]
        df.dropna(how='all', inplace=True)
        df['ingestion_timestamp'] = datetime.utcnow().isoformat()
        
        return df

    async def load_to_postgres(self, db: AsyncSession, table_name: str = "raw_ops_ingest") -> int:
        transformed_df = self.extract_and_transform()
        records = transformed_df.to_dict(orient="records")
        
        if records:
            query = text(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id SERIAL PRIMARY KEY,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute(query)
            
            for record in records:
                insert_stmt = text(f"INSERT INTO {table_name} (payload) VALUES (:payload)")
                await db.execute(insert_stmt, {"payload": json.dumps(record)})
            
            await db.commit()
        
        return len(records)
