"""
DIFF-03: "What I don't know yet" panel.

Surfaces REAL, currently-true limitations for a specific tenant -- every
entry here reflects an actual gap in what NexusFlow can currently tell
this tenant, derived from the same cheap, non-LLM signals other endpoints
already compute (get_ledger_chart_context, get_mrr_summary,
get_forecast_accuracy). Deliberately never calls an LLM-backed agent
(cfo-briefing, forecast, bi-summary, etc.) just to check an availability
flag -- that would mean a real network/API cost every time this panel
loads, to answer a question the cheap data-only signals already answer.

Two kinds of gaps: STRUCTURAL (true for every tenant today, because the
schema/product doesn't support it yet -- e.g. no customer-identity column)
and DATA-DEPENDENT (true only because THIS tenant's data doesn't clear a
real threshold yet -- e.g. not enough months of history).
"""
import logging
from fastapi import APIRouter, HTTPException, Depends

try:
    from backend import db_manager
    from backend.agents import predictive_forecaster
    from backend.auth import verify_jwt_and_get_client_id
except ImportError:
    import db_manager
    from agents import predictive_forecaster
    from auth import verify_jwt_and_get_client_id

router = APIRouter()
logger = logging.getLogger("nexusflow.gaps")

# Structural gaps: real, disclosed platform limitations that hold for every
# tenant today regardless of their data, because the underlying schema/
# product capability doesn't exist yet. Listed once here rather than
# re-derived per request since nothing about them is tenant-dependent.
_STRUCTURAL_GAPS = [
    {
        "key": "no_customer_identity",
        "title": "Per-customer analytics aren't available",
        "detail": (
            "The ledgers table has no customer/subscriber-identity column, "
            "so active-customer counts and real per-customer churn can't be "
            "computed -- only tenant-level aggregates."
        ),
    },
    {
        "key": "no_evidence_trail",
        "title": "Insights don't yet link back to their exact source rows",
        "detail": (
            "Agent narratives are grounded in real computed numbers, but "
            "there's no way yet to click an insight and see the specific "
            "ledger rows behind it."
        ),
    },
    {
        "key": "ai_usage_not_tenant_scoped",
        "title": "AI usage/cost metrics are platform-wide, not per-tenant",
        "detail": "Token and cost totals reflect the whole platform, not just this tenant, pending real multi-tenant RBAC.",
    },
]


@router.post("/api/v1/insights/known-gaps")
async def get_known_gaps(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        gaps = list(_STRUCTURAL_GAPS)
        context = await db_manager.get_ledger_chart_context(client_id)
        row_count = context.get("row_count", 0)

        if row_count == 0:
            gaps.insert(0, {
                "key": "no_data",
                "title": "No ledger data yet",
                "detail": "Upload a CSV ledger to unlock CFO briefings, forecasts, and every other analysis on this dashboard.",
            })
            return {"client_id": client_id, "row_count": 0, "gaps": gaps}

        mrr_summary = await db_manager.get_mrr_summary(client_id)
        if not mrr_summary.get("mrr_available"):
            gaps.append({
                "key": "mrr_unavailable",
                "title": "Real MRR isn't available yet",
                "detail": "No uploaded row has ever included a 'recurring' or 'is_recurring' column. Include it on your next upload to unlock true Monthly Recurring Revenue.",
            })

        # Forecast eligibility -- distinct-month count is already computed
        # by get_ledger_chart_context above; comparing it to the real
        # threshold here is free. Deliberately NOT calling
        # predictive_forecaster.generate_forecast() just to check this --
        # that would trigger a real LLM call on every dashboard load.
        distinct_months = len(context.get("monthly_totals", []))
        if distinct_months < predictive_forecaster.MIN_PERIODS_FOR_FORECAST:
            gaps.append({
                "key": "forecast_insufficient_history",
                "title": "Forecast isn't available yet",
                "detail": f"{distinct_months} distinct month(s) of history on file -- {predictive_forecaster.MIN_PERIODS_FOR_FORECAST} are required before a statistically meaningful trend can be forecast.",
            })

        unparseable = context.get("unparseable_date_count", 0)
        if unparseable:
            gaps.append({
                "key": "unparseable_dates",
                "title": f"{unparseable} transaction(s) have an unrecognized date",
                "detail": "These rows are excluded from every trend, forecast, and monthly figure until their dates are fixed and re-uploaded.",
            })

        accuracy = await db_manager.get_forecast_accuracy(client_id)
        pending_count = len(accuracy.get("pending", [])) if isinstance(accuracy, dict) else 0
        if pending_count:
            gaps.append({
                "key": "forecast_accuracy_pending",
                "title": f"{pending_count} forecast(s) awaiting their target month",
                "detail": "These forecasts haven't been checked against real outcomes yet because their target month hasn't happened. Accuracy will appear here once it has.",
            })

        return {"client_id": client_id, "row_count": row_count, "gaps": gaps}
    except Exception as e:
        logger.error(f"Failed to compute known gaps for tenant '{client_id}': {e}")
        raise HTTPException(status_code=502, detail="Unable to compute known gaps right now.")
