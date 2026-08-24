from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging

try:
    from backend.db_manager import get_total_ingested_rows
except ImportError:
    from db_manager import get_total_ingested_rows

router = APIRouter()
logger = logging.getLogger("nexusflow.metrics")

class IngestionMetrics(BaseModel):
    total_rows: int
    status: str

@router.get("/api/v1/metrics/ingestion", response_model=IngestionMetrics)
async def get_ingestion_metrics():
    try:
        total_rows = get_total_ingested_rows() 
        return {
            "total_rows": total_rows,
            "status": "success"
        }
    except Exception as e:
        logger.error(f"Error fetching ingestion metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch ingestion metrics")
