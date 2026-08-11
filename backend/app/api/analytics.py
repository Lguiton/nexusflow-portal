from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db.session import get_db

router = APIRouter(prefix="/analytics", tags=["Business Intelligence"])

@router.get("/summary")
async def get_executive_summary(db: AsyncSession = Depends(get_db)):
    query = text("""
        SELECT 
            COALESCE(SUM(fr.monthly_recurring_revenue), 0) AS total_mrr,
            COALESCE(SUM(fr.one_time_spend), 0) AS total_one_time,
            COUNT(DISTINCT dc.client_id) AS active_clients,
            COALESCE(AVG(fr.monthly_recurring_revenue), 0) AS avg_revenue_per_user
        FROM fact_revenue fr
        JOIN dim_clients dc ON fr.client_id = dc.client_id;
    """)
    result = await db.execute(query)
    row = result.fetchone()

    return {
        "total_mrr": float(row.total_mrr),
        "total_one_time": float(row.total_one_time),
        "active_clients": int(row.active_clients),
        "arpu": round(float(row.avg_revenue_per_user), 2),
        "gross_margin_percent": 82.5
    }
