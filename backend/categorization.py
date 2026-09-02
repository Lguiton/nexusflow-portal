"""
DIFF-06: auto-categorization suggestions.

Deterministic only, per founder decision (2026-08-23): every suggestion
comes from this SAME tenant's own already-categorized rows via real
keyword overlap (see db_manager._suggest_category_for) -- never an LLM
guess, never auto-applied. The frontend shows each suggestion with its
real confidence and match count; applying one is a separate, explicit,
user-confirmed call targeting one specific row_id (DIFF-01).
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

try:
    from backend import db_manager
    from backend.auth import verify_jwt_and_get_client_id, require_role, AuthenticatedUser
except ImportError:
    import db_manager
    from auth import verify_jwt_and_get_client_id, require_role, AuthenticatedUser

router = APIRouter()
logger = logging.getLogger("eivanta.categorization")


class ApplyCategorySuggestionRequest(BaseModel):
    row_id: int
    new_category: str


@router.post("/api/v1/data/category-suggestions", tags=["Ledger & Ingestion"])
async def get_category_suggestions(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        return await db_manager.suggest_category_fixes(client_id)
    except Exception as e:
        logger.error(f"Failed to compute category suggestions for tenant '{client_id}': {e}")
        raise HTTPException(status_code=502, detail="Unable to compute category suggestions right now.")


@router.post("/api/v1/data/apply-category-suggestion", tags=["Ledger & Ingestion"])
async def apply_category_suggestion_endpoint(
    req: ApplyCategorySuggestionRequest,
    # RBAC-01: mutates real ledger data -- viewer excluded.
    user: AuthenticatedUser = Depends(require_role("owner", "admin", "member")),
):
    client_id = user.client_id
    try:
        updated = await db_manager.apply_category_suggestion(client_id, req.row_id, req.new_category)
        if not updated:
            raise HTTPException(
                status_code=404,
                detail="No matching row found for that row_id -- it may belong to a legacy row with no id, a different tenant, or may have already been re-categorized.",
            )
        return {"client_id": client_id, "row_id": req.row_id, "new_category": req.new_category, "updated": True}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to apply category suggestion for tenant '{client_id}': {e}")
        raise HTTPException(status_code=502, detail="Unable to apply category suggestion right now.")
