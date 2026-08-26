import os
import json
import logging
import duckdb
import numpy as np
from scipy import stats
from typing import Dict, Any, List, Tuple
from dotenv import load_dotenv
from openai import OpenAI

try:
    from backend.db_manager import DB_PATH, get_db_lock, log_ai_usage_sync, log_forecast_snapshot_sync
    from backend.model_registry import get_model
except ImportError:
    from db_manager import DB_PATH, get_db_lock, log_ai_usage_sync, log_forecast_snapshot_sync
    from model_registry import get_model

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

logger = logging.getLogger("eivanta.predictive_forecaster")

# AI-03: previously no explicit request timeout at all -- a hung OpenAI
# request had no client-side bound and would block this agent's execution
# indefinitely (or until whatever called it eventually gave up). max_retries
# matches the openai SDK's own default (2) -- made explicit here rather than
# left implicit, so it's a documented decision, not an accident.
AI_REQUEST_TIMEOUT_SECONDS = 30.0
AI_MAX_RETRIES = 2

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key, timeout=AI_REQUEST_TIMEOUT_SECONDS, max_retries=AI_MAX_RETRIES) if api_key else None

# FIN-04 decisions made explicit here rather than silently assumed --
# revisit these deliberately, don't just accept them because they're in
# code:
MIN_PERIODS_FOR_FORECAST = 4   # fewer than this and a linear trend is statistically meaningless
FORECAST_HORIZON_MONTHS = 3    # "next quarter" -- matches the prior Q4 framing

# FIN-05 "data science duties" folded into Predictive Forecaster, per
# founder decision -- as a TENANT-LEVEL REVENUE-RISK PROXY, explicitly NOT
# customer-level churn. The ledgers table (client_id, date, category,
# amount, description) has no customer/subscriber identity column at all,
# so there is no way to know whether any specific customer kept
# transacting or stopped -- real per-customer churn cannot be computed
# from this schema regardless of model sophistication. What follows is
# real, computed signal from actual monthly revenue (decline streaks,
# recent-vs-overall trend deceleration) -- not narration, but also not a
# formally calibrated churn model. These thresholds are provisional
# heuristics, same category as MIN_PERIODS_FOR_FORECAST/
# FORECAST_HORIZON_MONTHS above -- explicit so they can be deliberately
# revisited, not silently treated as authoritative.
RECENT_WINDOW_MONTHS = 3            # "recent" trend window for deceleration comparison
CONSECUTIVE_DECLINE_MODERATE = 2    # consecutive declining months considered moderate risk
CONSECUTIVE_DECLINE_ELEVATED = 3    # consecutive declining months considered elevated risk
MATERIALLY_DECLINING_PCT = -1.0     # growth rate below this (%/month) counts as a real
                                     # decline signal -- above this (even if technically
                                     # negative) is treated as noise around a flat trend,
                                     # not a real decline. Verified via test: without this,
                                     # a flat/noisy revenue series with a near-zero negative
                                     # slope (pure statistical noise) was flagged MODERATE.


def _load_monthly_revenue(safe_client_id: str) -> Tuple[List[str], List[float], int, int, bool, str]:
    """
    Returns (periods, revenue, total_rows, skipped_unparseable_dates,
    db_failed, failure_reason). Real per-tenant, per-month revenue from
    actual ledger data -- not a lifetime lump sum.

    FIXED: previously opened its own connection with NO synchronization
    against db_manager.py's shared lock at all, and any exception here
    (connection failure OR query failure) was silently indistinguishable
    from a genuinely empty tenant -- same masked-failure pattern already
    fixed in virtual_cfo.py/data_engineer.py/bi_engineer.py/saas_strategist.py.
    Now serialized through the same shared lock via db_manager.get_db_lock(),
    and returns db_failed/failure_reason so the caller can tell a real
    failure apart from a real empty result.
    """
    periods: List[str] = []
    revenue: List[float] = []
    total_rows = 0
    skipped_unparseable_dates = 0
    db_failed = False
    failure_reason = ""

    if os.path.exists(DB_PATH):
        lock = get_db_lock()
        with lock:
            conn = None
            try:
                conn = duckdb.connect(DB_PATH, read_only=True)
            except Exception as e:
                logger.error(f"Failed to open DuckDB at {DB_PATH}: {e}")
                db_failed = True
                failure_reason = f"database connection failed: {e}"

            if conn:
                try:
                    tables = conn.execute("SHOW TABLES").fetchall()
                    table_names = [t[0] for t in tables]
                    if "ledgers" in table_names:
                        counts = conn.execute(
                            """
                            SELECT COUNT(*), SUM(CASE WHEN TRY_CAST(date AS DATE) IS NULL THEN 1 ELSE 0 END)
                            FROM ledgers WHERE client_id = ? AND amount > 0
                            """,
                            [safe_client_id]
                        ).fetchone()
                        total_rows = int(counts[0] or 0)
                        skipped_unparseable_dates = int(counts[1] or 0)

                        rows = conn.execute(
                            """
                            SELECT strftime(period, '%Y-%m') AS period_label, SUM(amount) AS revenue
                            FROM (
                                SELECT date_trunc('month', TRY_CAST(date AS DATE)) AS period, amount
                                FROM ledgers
                                WHERE client_id = ? AND amount > 0
                            ) sub
                            WHERE period IS NOT NULL
                            GROUP BY period, period_label
                            ORDER BY period
                            """,
                            [safe_client_id]
                        ).fetchall()
                        for period_label, rev in rows:
                            periods.append(period_label)
                            revenue.append(float(rev))
                except Exception as e:
                    logger.error(f"DuckDB query error in Forecaster: {e}")
                    db_failed = True
                    failure_reason = f"query failed: {e}"
                finally:
                    conn.close()

    return periods, revenue, total_rows, skipped_unparseable_dates, db_failed, failure_reason


def _linear_trend_forecast(periods: List[str], revenue: List[float]) -> Dict[str, Any]:
    """
    Real, tested linear-trend regression (scipy.stats.linregress) with a
    genuine 95% prediction interval -- not a hardcoded growth constant.
    """
    x = np.arange(len(periods))
    y = np.array(revenue)
    n = len(x)

    slope, intercept, r_value, _, _ = stats.linregress(x, y)
    predicted = intercept + slope * x
    residuals = y - predicted
    residual_std = np.sqrt(np.sum(residuals ** 2) / (n - 2))

    future_x = np.arange(n, n + FORECAST_HORIZON_MONTHS)
    forecast_values = intercept + slope * future_x

    t_val = stats.t.ppf(0.975, df=n - 2)
    mean_x = np.mean(x)
    sum_sq_x = np.sum((x - mean_x) ** 2)

    forecast_periods = []
    for xf, fv in zip(future_x, forecast_values):
        se_pred = residual_std * np.sqrt(1 + 1 / n + (xf - mean_x) ** 2 / sum_sq_x)
        half_width = t_val * se_pred
        forecast_periods.append({
            "months_ahead": int(xf - n + 1),
            "projected_revenue": round(float(fv), 2),
            "ci_lower_95": round(float(fv - half_width), 2),
            "ci_upper_95": round(float(fv + half_width), 2),
        })

    avg_revenue = float(np.mean(y))
    growth_rate_pct_per_period = (slope / avg_revenue * 100) if avg_revenue else 0.0

    return {
        "method": "linear_trend_regression",
        "r_squared": round(float(r_value ** 2), 4),
        "growth_rate_pct_per_period": round(float(growth_rate_pct_per_period), 2),
        "forecast": forecast_periods,
        "projected_next_quarter_revenue": round(float(sum(p["projected_revenue"] for p in forecast_periods)), 2),
    }


def _assess_revenue_risk(revenue: List[float], overall_growth_rate_pct: float) -> Dict[str, Any]:
    """
    Real, computed tenant-level revenue-risk proxy -- NOT customer-level
    churn (see module header comment for why that can't be computed from
    this schema). Three signals, all derived directly from the same real
    monthly revenue series already loaded for forecasting -- no LLM
    involved in the scoring itself:

      - consecutive_declining_months: how many of the most recent months
        each fell below the prior month, counted back from the most
        recent month until the streak breaks.
      - recent_growth_rate_pct_per_month: a fresh linear-trend slope over
        just the most recent RECENT_WINDOW_MONTHS months, independent of
        the full-history trend.
      - deceleration_detected: True when the recent trend is more
        negative than the overall trend -- i.e. decline is intensifying,
        or growth is stalling out, rather than staying stable/improving.

    risk_level is a simple, transparent combination of the above using the
    named thresholds at the top of this file -- a provisional heuristic,
    not a calibrated statistical risk score.
    """
    consecutive_declining_months = 0
    for i in range(len(revenue) - 1, 0, -1):
        if revenue[i] < revenue[i - 1]:
            consecutive_declining_months += 1
        else:
            break

    window = min(RECENT_WINDOW_MONTHS, len(revenue))
    recent_growth_rate_pct = None
    if window >= 2:
        recent_x = np.arange(window)
        recent_y = np.array(revenue[-window:])
        recent_slope, _, _, _, _ = stats.linregress(recent_x, recent_y)
        recent_avg = float(np.mean(recent_y))
        recent_growth_rate_pct = round((recent_slope / recent_avg * 100) if recent_avg else 0.0, 2)

    deceleration_detected = bool(
        recent_growth_rate_pct is not None
        and recent_growth_rate_pct < overall_growth_rate_pct
        and recent_growth_rate_pct < MATERIALLY_DECLINING_PCT
    )

    if consecutive_declining_months >= CONSECUTIVE_DECLINE_ELEVATED and overall_growth_rate_pct < MATERIALLY_DECLINING_PCT:
        risk_level = "ELEVATED"
    elif (
        consecutive_declining_months >= CONSECUTIVE_DECLINE_MODERATE
        or overall_growth_rate_pct < MATERIALLY_DECLINING_PCT
        or deceleration_detected
    ):
        risk_level = "MODERATE"
    else:
        risk_level = "LOW"

    return {
        "risk_level": risk_level,
        "consecutive_declining_months": consecutive_declining_months,
        "recent_growth_rate_pct_per_month": recent_growth_rate_pct,
        "overall_growth_rate_pct_per_month": round(overall_growth_rate_pct, 2),
        "deceleration_detected": deceleration_detected,
        "note": (
            "Tenant-level revenue-risk proxy derived from real monthly revenue "
            "trend/volatility signals -- NOT customer-level churn (the ledgers "
            "table has no customer/subscriber identity column to compute that from)."
        ),
    }


def _error_state_response(reason: str) -> Dict[str, Any]:
    """
    FIXED (same masked-failure bug found and fixed this update in
    virtual_cfo.py, data_engineer.py, bi_engineer.py, and saas_strategist.py
    -- predictive_forecaster.py had the identical pattern and was missed in
    that pass). Distinct from the NO_DATA response below: this means the
    forecast could NOT be computed -- a real connection or query failure --
    not that this tenant genuinely has zero revenue rows.
    """
    return {
        "agent": "Predictive Forecaster Agent #07",
        "status": "ERROR",
        "baseline_revenue": None,
        "projected_q4_revenue": None,
        "projected_growth_rate": None,
        "projections": [
            f"The forecast could not be generated right now ({reason}). This is "
            "different from an empty tenant -- please retry; if it keeps "
            "happening, check the backend logs for the underlying error."
        ]
    }


def generate_forecast(client_id: str = "default_client") -> Dict[str, Any]:
    """
    Agent #07 (Predictive Forecaster).

    Real per-month revenue history run through a real linear-trend
    regression with a genuine 95% prediction interval, plus a real
    tenant-level revenue-risk proxy (see _assess_revenue_risk) -- the FIN-05
    "data science" duties folded into this agent per founder decision.
    Previous version multiplied a lifetime revenue total by a hardcoded
    1.15 and asked an LLM to narrate a fabricated "confidence interval" --
    see chat history for the full explanation of why that violated SRS
    FR-3.1/FR-3.3.
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    periods, revenue, total_rows, skipped_dates, db_failed, failure_reason = _load_monthly_revenue(safe_client_id)

    # FIXED (masked-failure bug): a real connection/query failure is no
    # longer indistinguishable from a genuinely empty tenant.
    if db_failed:
        return _error_state_response(failure_reason)

    if total_rows == 0:
        return {
            "agent": "Predictive Forecaster Agent #07",
            "status": "NO_DATA",
            "baseline_revenue": 0.0,
            "projected_q4_revenue": None,
            "projected_growth_rate": None,
            "projections": [
                "No revenue data has been ingested yet for this tenant. Upload a CSV ledger to enable forecasting."
            ]
        }

    baseline_revenue = round(sum(revenue), 2)

    if len(periods) < MIN_PERIODS_FOR_FORECAST:
        return {
            "agent": "Predictive Forecaster Agent #07",
            "status": "INSUFFICIENT_HISTORY",
            "baseline_revenue": baseline_revenue,
            "periods_available": len(periods),
            "periods_required": MIN_PERIODS_FOR_FORECAST,
            "projected_q4_revenue": None,
            "projected_growth_rate": None,
            "projections": [
                f"Only {len(periods)} distinct month(s) of revenue history are available; "
                f"at least {MIN_PERIODS_FOR_FORECAST} are needed for a statistically meaningful trend forecast. "
                f"Total recorded revenue to date: ${baseline_revenue:,.2f}."
            ]
        }

    trend = _linear_trend_forecast(periods, revenue)
    revenue_risk = _assess_revenue_risk(revenue, trend["growth_rate_pct_per_period"])

    # FIN-04: store this run's per-month projections so get_forecast_accuracy()
    # can later compare them against what actually happened once those
    # months' real ledger data exists. periods[-1] is the last real
    # historical month -- forecast_by_month's months_ahead values are
    # relative to it.
    log_forecast_snapshot_sync(safe_client_id, periods[-1], trend["method"], trend["r_squared"], trend["forecast"])

    system_prompt = f"""
    You are Agent #07, Eivanta's Predictive Forecaster.
    Tenant: {safe_client_id}
    Real computed data -> {len(periods)} months of history, total revenue: ${baseline_revenue:,.2f}, trend R-squared: {trend['r_squared']}, growth rate per month: {trend['growth_rate_pct_per_period']}%, projected next-quarter revenue: ${trend['projected_next_quarter_revenue']:,.2f}.
    Real revenue-risk signal (tenant-level, NOT customer churn) -> risk_level: {revenue_risk['risk_level']}, {revenue_risk['consecutive_declining_months']} consecutive declining month(s), recent trend {revenue_risk['recent_growth_rate_pct_per_month']}%/month vs overall {revenue_risk['overall_growth_rate_pct_per_month']}%/month, deceleration_detected: {revenue_risk['deceleration_detected']}.

    These numbers come from a real linear regression and real trend comparison over actual monthly revenue -- do not invent any additional statistics, and do not describe the risk signal as customer churn. Summarize what these real numbers mean for the business.

    Respond in pure JSON:
    {{
      "agent": "Predictive Forecaster Agent #07",
      "status": "FORECASTED",
      "projections": ["Insight 1...", "Insight 2...", "Insight 3..."]
    }}
    """

    projections = None
    try:
        if not client:
            raise ValueError("OpenAI client not initialized.")
        model = get_model("predictive_forecaster")
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Summarize this real forecast."}
            ],
            temperature=0.3
        )
        usage = getattr(response, "usage", None)
        if usage:
            log_ai_usage_sync(
                safe_client_id, "predictive_forecaster", model,
                getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0), getattr(usage, "total_tokens", 0),
                "SUCCESS"
            )
        result = json.loads(response.choices[0].message.content)
        candidate = result.get("projections")
        if isinstance(candidate, list) and len(candidate) > 0:
            projections = candidate
        else:
            logger.error(f"Unexpected forecaster response shape from LLM: {result!r}")
    except Exception as e:
        logger.error(f"Forecaster LLM error: {e}")

    if projections is None:
        projections = [
            f"Revenue trend over the last {len(periods)} months: {trend['growth_rate_pct_per_period']:+.2f}% per month "
            f"(R-squared {trend['r_squared']}).",
            f"Projected next-quarter revenue: ${trend['projected_next_quarter_revenue']:,.2f}.",
            f"Total recorded revenue to date: ${baseline_revenue:,.2f}.",
            f"Revenue-risk signal: {revenue_risk['risk_level']} ({revenue_risk['consecutive_declining_months']} consecutive declining month(s))."
        ]

    return {
        "agent": "Predictive Forecaster Agent #07",
        "status": "FORECASTED",
        "baseline_revenue": baseline_revenue,
        "periods_used": len(periods),
        "periods_skipped_unparseable_date": skipped_dates,
        "method": trend["method"],
        "r_squared": trend["r_squared"],
        "projected_growth_rate": trend["growth_rate_pct_per_period"],
        "forecast_by_month": trend["forecast"],
        "projected_q4_revenue": trend["projected_next_quarter_revenue"],
        "revenue_risk": revenue_risk,
        "projections": projections
    }
