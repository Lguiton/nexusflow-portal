"""
DIFF-02: Assumption ledger.

Surfaces the REAL, already-disclosed numeric constants and methodology
choices this platform's calculations depend on -- read LIVE from the
modules that actually use them, never hand-copied values that could drift
out of sync with the real code the moment someone tunes a threshold.

Platform-wide, not tenant-scoped -- these are code-level constants, not
per-tenant data. Requires a valid token (same posture as
/api/v1/metrics/ai-usage and friends: authenticated but not yet gated
behind a real admin/RBAC tier -- see metrics.py's own notes on this).
"""
import logging
from fastapi import APIRouter, HTTPException, Depends

try:
    from backend.agents import virtual_cfo, predictive_forecaster
except ImportError:
    from agents import virtual_cfo, predictive_forecaster

try:
    from backend.auth import verify_jwt_and_get_client_id
except ImportError:
    from auth import verify_jwt_and_get_client_id

try:
    from backend import accounts
except ImportError:
    import accounts

router = APIRouter()
logger = logging.getLogger("eivanta.assumptions")


def _build_assumptions() -> dict:
    """
    Separated from the endpoint so it can be unit-tested without spinning
    up FastAPI/JWT machinery -- pure function, no request/auth dependency.
    """
    return {
        "numeric_assumptions": [
            {
                "key": "assumed_cash_reserves",
                "label": "Assumed Cash Reserves",
                "value": virtual_cfo.ASSUMED_CASH_RESERVES,
                "unit": "usd",
                "used_by": "Virtual CFO -- Cash Runway; Scenario Modeler -- baseline & projected runway (overridable per request via cash_reserves)",
                "description": (
                    "Cash runway (assumed_cash_reserves / burn_rate) uses this "
                    "PLACEHOLDER reserve figure, not a real bank balance -- "
                    "Eivanta has no bank/accounting integration to pull an "
                    "actual cash position from yet. Every runway figure shown "
                    "anywhere is only as real as this number, unless a caller "
                    "explicitly overrides it (Scenario Modeler's cash_reserves "
                    "parameter is the one place that's currently possible)."
                ),
            },
            {
                "key": "min_periods_for_forecast",
                "label": "Minimum Months of History Required to Forecast",
                "value": predictive_forecaster.MIN_PERIODS_FOR_FORECAST,
                "unit": "months",
                "used_by": "Predictive Forecaster",
                "description": (
                    "Fewer distinct months of ledger history than this, and a "
                    "linear trend is not computed -- reported as "
                    "INSUFFICIENT_HISTORY instead of a fabricated projection."
                ),
            },
            {
                "key": "forecast_horizon_months",
                "label": "Forecast Horizon",
                "value": predictive_forecaster.FORECAST_HORIZON_MONTHS,
                "unit": "months",
                "used_by": "Predictive Forecaster",
                "description": "How many months forward each forecast projects.",
            },
            {
                "key": "recent_window_months",
                "label": "Recent-Trend Window (Revenue-Risk Proxy)",
                "value": predictive_forecaster.RECENT_WINDOW_MONTHS,
                "unit": "months",
                "used_by": "Predictive Forecaster -- Revenue-Risk Proxy",
                "description": (
                    "Width of the 'recent' window compared against the overall "
                    "trend to detect growth-rate deceleration."
                ),
            },
            {
                "key": "consecutive_decline_moderate",
                "label": "Moderate-Risk Threshold",
                "value": predictive_forecaster.CONSECUTIVE_DECLINE_MODERATE,
                "unit": "consecutive declining months",
                "used_by": "Predictive Forecaster -- Revenue-Risk Proxy",
                "description": "This many consecutive declining months is flagged MODERATE risk.",
            },
            {
                "key": "consecutive_decline_elevated",
                "label": "Elevated-Risk Threshold",
                "value": predictive_forecaster.CONSECUTIVE_DECLINE_ELEVATED,
                "unit": "consecutive declining months",
                "used_by": "Predictive Forecaster -- Revenue-Risk Proxy",
                "description": "This many consecutive declining months is flagged ELEVATED risk.",
            },
            {
                "key": "login_lockout_policy",
                "label": "Login Lockout Policy (AUTH-05)",
                "value": f"{accounts.MAX_FAILED_LOGIN_ATTEMPTS} attempts / {accounts.LOGIN_LOCKOUT_MINUTES} min",
                "unit": "attempts / minutes",
                "used_by": "Login (POST /api/v1/auth/login)",
                "description": (
                    "This many consecutive wrong-password attempts against a real "
                    "account locks it for this many minutes. A moderate starting "
                    "default, not yet tuned against real attack traffic (none "
                    "exists for this product yet) -- revisit once it does."
                ),
            },
            {
                "key": "materially_declining_pct",
                "label": "Materiality Threshold for Decline",
                "value": predictive_forecaster.MATERIALLY_DECLINING_PCT,
                "unit": "% per month",
                "used_by": "Predictive Forecaster -- Revenue-Risk Proxy",
                "description": (
                    "A recent monthly growth rate below this percentage counts "
                    "as a materially declining trend, not just ordinary noise."
                ),
            },
        ],
        "methodology_notes": [
            {
                "key": "revenue_cogs_opex_classification",
                "label": "Revenue / COGS / OPEX Classification",
                "used_by": "Virtual CFO -- Gross Margin, Burn Rate",
                "description": (
                    "Transactions are classified by sign and a category-name "
                    "keyword heuristic, not a formal chart-of-accounts mapping. "
                    "Gross margin and burn rate are only as accurate as this "
                    "heuristic."
                ),
            },
            {
                "key": "mrr_definition",
                "label": "Monthly Recurring Revenue Definition",
                "used_by": "Finance KPIs",
                "description": (
                    "MRR sums positive-amount transactions a tenant explicitly "
                    "flagged recurring=true, dated in the current calendar "
                    "month. This is transaction-based, not subscription-"
                    "contract-based -- there is no billing-cycle/contract-value "
                    "table to compute 'currently active recurring value' "
                    "independent of what was actually invoiced this month."
                ),
            },
            {
                "key": "revenue_risk_not_churn",
                "label": "Revenue-Risk Proxy Is Not Customer Churn",
                "used_by": "Predictive Forecaster",
                "description": (
                    "The ledgers table has no customer/subscriber-identity "
                    "column, so real per-customer churn cannot be computed. "
                    "What's shown is a tenant-level revenue trend/volatility "
                    "signal instead -- explicitly not churn."
                ),
            },
            {
                "key": "ai_usage_platform_wide",
                "label": "AI Usage & Cost Metrics Are Platform-Wide",
                "used_by": "AI Usage Telemetry",
                "description": (
                    "Token/cost totals are not yet scoped per tenant -- they "
                    "reflect the whole platform, pending real multi-tenant RBAC."
                ),
            },
            {
                "key": "confidence_score_scope",
                "label": "Confidence Score Is Not a Statistical Certainty (Except Forecasts)",
                "used_by": "Cognitive Search / Orchestrator",
                "description": (
                    "confidence_score is a real computed r-squared for "
                    "forecast results, but a simple success/failure signal "
                    "(1.0 or 0.0) for every other agent -- not a calibrated "
                    "probability of correctness."
                ),
            },
        ],
    }


@router.get("/api/v1/assumptions")
async def get_assumptions(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        return _build_assumptions()
    except Exception as e:
        logger.error(f"Failed to build assumption ledger: {e}")
        raise HTTPException(status_code=500, detail="Failed to load assumption ledger")
