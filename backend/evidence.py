"""
DIFF-01: evidence trail / insight-to-source-row linking.

Scope of this pass, stated plainly rather than implied: this gives every
ledger row a real, stable identity (row_id -- see db_manager.init_db's
migration) and a real drill-down endpoint to browse the exact rows behind
a category/month. It does NOT (yet) rewrite every agent's LLM-generated
narrative to cite specific row_ids inline -- that would mean touching each
agent's prompt/response-shape individually, a substantially larger change.
What's here is the real, honest foundation: a genuine way to go from "this
category/month total" to "these are the literal rows that produced it."
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

try:
    from backend import db_manager
    from backend.auth import verify_jwt_and_get_client_id
except ImportError:
    import db_manager
    from auth import verify_jwt_and_get_client_id

router = APIRouter()
logger = logging.getLogger("eivanta.evidence")


class LedgerRowsRequest(BaseModel):
    category: Optional[str] = None
    month: Optional[str] = None
    limit: int = 200
    # Track 5 global time-range selector: a real inclusive date range,
    # independent of the exact "month" match above.
    date_from: Optional[str] = None
    date_to: Optional[str] = None


@router.post("/api/v1/finance/ledger-rows", tags=["Ledger & Ingestion"])
async def get_ledger_rows_endpoint(
    req: LedgerRowsRequest = LedgerRowsRequest(),
    client_id: str = Depends(verify_jwt_and_get_client_id),
):
    try:
        return await db_manager.get_ledger_rows(
            client_id, category=req.category, month=req.month, limit=req.limit,
            date_from=req.date_from, date_to=req.date_to,
        )
    except Exception as e:
        logger.error(f"Failed to fetch ledger rows for tenant '{client_id}': {e}")
        raise HTTPException(status_code=502, detail="Unable to load ledger rows right now.")
