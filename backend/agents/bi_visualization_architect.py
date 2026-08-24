
import asyncio
import json
import logging
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI

try:
    from backend.db_manager import log_ai_usage_sync
    from backend.model_registry import get_model
except ImportError:
    from db_manager import log_ai_usage_sync
    from model_registry import get_model

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)
logger = logging.getLogger("nexusflow.bi_visualization_architect")

# AI-03: previously no explicit request timeout at all. max_retries matches
# the openai SDK's own default (2), made explicit here rather than left
# implicit.
AI_REQUEST_TIMEOUT_SECONDS = 30.0
AI_MAX_RETRIES = 2

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key, timeout=AI_REQUEST_TIMEOUT_SECONDS, max_retries=AI_MAX_RETRIES) if api_key else None
 
 
def _summarize_with_llm(client_id: str, query: str, chart_type: str, recharts_config: dict, context: dict) -> List[str]:
    """
    Optional commentary layer only. The chart type and recharts_config
    passed in are already real, data-grounded decisions by the time this
    runs -- the model is asked to comment on why they fit, never to invent
    a different chart type or different columns.
    """
    if not client:
        return ["OpenAI client not configured -- no narrative commentary available; the chart recommendation above was derived directly from this tenant's real ledger data regardless."]
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    system_prompt = f"""
    You are the BI Visualization Architect. Client: {safe_client_id}.
    A chart type and Recharts config were already chosen deterministically
    from this tenant's REAL ledger data: chart_type={chart_type},
    recharts_config={json.dumps(recharts_config)}.
    Real data context: {json.dumps(context, default=str)}
    Original request: {query}
    Provide up to 3 short, practical observations about why this chart
    suits this real data, or a caveat worth knowing -- do not propose a
    different chart type or invent different column names.
    Respond STRICTLY in JSON: {{"insights": ["..."]}}
    """
    try:
        model = get_model("bi_visualization_architect")
        res = client.chat.completions.create(
            model=model, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system_prompt}], temperature=0.2
        )
        usage = getattr(res, "usage", None)
        if usage:
            log_ai_usage_sync(
                safe_client_id, "bi_visualization_architect", model,
                getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0), getattr(usage, "total_tokens", 0),
                "SUCCESS"
            )
        parsed = json.loads(res.choices[0].message.content)
        insights = parsed.get("insights")
        if isinstance(insights, list):
            return [str(i) for i in insights]
        return []
    except Exception as e:
        logger.warning(f"BI Visualization Architect commentary generation failed (non-fatal, chart config above is unaffected): {e}")
        return []
 
 
def _choose_chart(query: str, context: Dict[str, Any]) -> tuple:
    """
    Deterministic chart-type selection grounded in this tenant's real data
    shape -- not an LLM guess. Returns (chart_type, recharts_config,
    rationale_basis).
    """
    category_breakdown = context.get("category_breakdown", [])
    monthly_totals = context.get("monthly_totals", [])
    q = query.lower()
 
    wants_trend = any(kw in q for kw in ["trend", "over time", "monthly", "growth", "timeline", "history"])
 
    if wants_trend and len(monthly_totals) >= 2:
        return (
            "line",
            {"xAxis": "month", "dataKeys": ["total_amount"], "data_source": "monthly_totals"},
            f"{len(monthly_totals)} real monthly totals from {context.get('date_min')} to {context.get('date_max')}",
        )
    if len(category_breakdown) > 8:
        return (
            "pareto",
            {"xAxis": "category", "dataKeys": ["total_amount"], "data_source": "category_breakdown"},
            f"{len(category_breakdown)} real categories -- a Pareto view highlights the largest contributors",
        )
    if len(category_breakdown) > 1:
        return (
            "bar",
            {"xAxis": "category", "dataKeys": ["total_amount"], "data_source": "category_breakdown"},
            f"{len(category_breakdown)} real categories from this tenant's actual ledger",
        )
    return (
        "bar",
        {"xAxis": "category", "dataKeys": ["total_amount", "entry_count"], "data_source": "category_breakdown"},
        "only one real category present -- showing amount and entry count together",
    )
 
 
async def generate_chart_suite(client_id: str = "default_client") -> Dict[str, Any]:
    """
    Real, deterministic multi-chart payload for this tenant -- no LLM
    involved (unlike execute_task's single ad hoc query flow, which picks
    ONE recommended chart type for one query). This returns every chart
    the dashboard's chart-suite widget renders in one call:
      - category_breakdown: pie (or pareto once there are enough
        categories to warrant highlighting top contributors) from real
        category totals.
      - monthly_trend: a real line chart of monthly revenue, only included
        once at least 2 distinct months are on file (a "trend" of one data
        point isn't a trend).
      - amount_distribution: a real transaction-amount histogram via
        db_manager.get_amount_distribution -- no such capability existed
        anywhere in this codebase before this function.
    Each section is independently omitted (not fabricated) if the
    underlying real data doesn't support it; the whole response is
    NO_DATA only when the tenant has no ledger rows at all.

    IMPORTANT (fixed after a live crash): this function is `async` and
    must be awaited DIRECTLY from the running event loop -- e.g.
    `await generate_chart_suite(client_id)` in main.py, never wrapped in
    `asyncio.to_thread(...)` calling `asyncio.run(...)` internally the way
    an earlier version of this function did (matching execute_task's
    existing pattern below). db_manager.get_db_lock() returns a MODULE-
    LEVEL SINGLETON `asyncio.Lock`, lazily bound to whichever event loop
    first acquires it, for the lifetime of the process. `asyncio.run()`
    creates and destroys its own throwaway event loop every call -- so a
    sync wrapper calling `asyncio.run(get_ledger_chart_context(...))` from
    a worker thread binds that shared lock to a loop that no longer exists
    the moment the call returns. Every OTHER caller of that same lock
    (including plain `await get_ledger_chart_context(...)` from a normal
    FastAPI endpoint on the main uvicorn loop) then fails with exactly the
    "Lock object ... is bound to a different event loop" error seen live --
    this is what broke the KPI Summary and Analytics Summary endpoints too,
    not anything wrong in their own code. See the note left in main.py's
    /api/v1/bi/chart-suite endpoint and the reply given alongside this fix
    for the larger, still-open architectural question this exposes:
    execute_task (below) and orchestrator.py's telemetry/broadcast helpers
    still use the asyncio.run()-in-a-thread pattern against this same
    shared lock, and will re-trigger this once they're exercised again
    (e.g. once /api/search works again after langgraph is installed).
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")

    try:
        from backend.db_manager import get_ledger_chart_context, get_amount_distribution
    except ImportError:
        from db_manager import get_ledger_chart_context, get_amount_distribution

    try:
        context = await get_ledger_chart_context(safe_client_id)
    except Exception as e:
        logger.error(f"BI Visualization Architect: failed to fetch ledger context for {safe_client_id}: {e}")
        return {"agent": "BI Visualization Architect", "status": "ERROR", "charts": {}, "insights": [str(e)]}

    if context.get("row_count", 0) == 0:
        return {
            "agent": "BI Visualization Architect",
            "status": "NO_DATA",
            "charts": {},
            "insights": ["No ledger data has been ingested for this tenant yet -- upload a ledger to generate charts."]
        }

    category_breakdown = context.get("category_breakdown", [])
    monthly_totals = context.get("monthly_totals", [])
    charts: Dict[str, Any] = {}

    if category_breakdown:
        cat_chart_type = "pareto" if len(category_breakdown) > 8 else "pie"
        charts["category_breakdown"] = {
            "chart_type": cat_chart_type,
            "config": {"xAxisKey": "category", "dataKeys": ["total_amount"]},
            "data": category_breakdown,
        }

    if len(monthly_totals) >= 2:
        charts["monthly_trend"] = {
            "chart_type": "line",
            "config": {"xAxisKey": "month", "dataKeys": ["total_amount"]},
            "data": monthly_totals,
        }

    try:
        distribution = await get_amount_distribution(safe_client_id)
    except Exception as e:
        logger.error(f"BI Visualization Architect: failed to compute amount distribution for {safe_client_id}: {e}")
        distribution = {"row_count": 0, "bins": []}

    if distribution.get("bins"):
        charts["amount_distribution"] = {
            "chart_type": "histogram",
            "config": {"xAxisKey": "range_label", "dataKeys": ["count"]},
            "data": distribution["bins"],
        }

    insights = [
        f"{context.get('row_count', 0)} real ledger record(s) across "
        f"{len(category_breakdown)} categor{'y' if len(category_breakdown) == 1 else 'ies'}."
    ]
    if len(monthly_totals) >= 2:
        insights.append(
            f"Monthly revenue trend spans {monthly_totals[0]['month']} to {monthly_totals[-1]['month']}."
        )
    else:
        insights.append(
            "Fewer than two distinct months on file -- monthly trend chart withheld until more history accumulates."
        )
    if distribution.get("bins"):
        insights.append(
            f"Transaction amounts grouped into {len(distribution['bins'])} real bins from this tenant's actual ledger."
        )

    return {
        "agent": "BI Visualization Architect",
        "status": "COMPLETED",
        "charts": charts,
        "insights": insights,
    }


def execute_task(client_id: str = "default_client", query: str = "") -> Dict[str, Any]:
    """
    Real chart-type recommendation grounded in this tenant's actual ledger
    data (via db_manager.get_ledger_chart_context) -- not an invented
    schema. Returns NO_DATA (matching the status convention used elsewhere
    in this codebase) rather than fabricating a chart for a tenant with no
    ingested data yet.
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
 
    try:
        from backend.db_manager import get_ledger_chart_context
    except ImportError:
        from db_manager import get_ledger_chart_context
 
    # Detect "already inside a running event loop" via an explicit check,
    # rather than a bare `except RuntimeError` around asyncio.run() --
    # asyncio.run() itself raises plain RuntimeError for this specific
    # case, but the wrapped coroutine could also raise RuntimeError for a
    # completely unrelated reason, and a blanket catch would mislabel that
    # real failure with a misleading "nested event loop" message. The
    # established call path (main.py -> asyncio.to_thread -> execute_task)
    # always runs this in a fresh worker thread with no loop of its own, so
    # this branch is not expected to trigger today.
    try:
        asyncio.get_running_loop()
        logger.error(f"BI Visualization Architect: called from within a running event loop for {safe_client_id}; cannot fetch chart context synchronously.")
        return {
            "agent": "BI Visualization Architect",
            "status": "ERROR",
            "insights": ["Internal error: chart context could not be retrieved in this execution context."]
        }
    except RuntimeError:
        pass  # no running loop -- the expected case; safe to call asyncio.run() below.
 
    try:
        context = asyncio.run(get_ledger_chart_context(safe_client_id))
    except Exception as e:
        logger.error(f"BI Visualization Architect: failed to fetch ledger context for {safe_client_id}: {e}")
        return {"agent": "BI Visualization Architect", "status": "ERROR", "insights": [str(e)]}
 
    if context.get("row_count", 0) == 0:
        return {
            "agent": "BI Visualization Architect",
            "status": "NO_DATA",
            "insights": ["No ledger data has been ingested for this tenant yet -- upload a ledger before requesting a chart."]
        }
 
    chart_type, recharts_config, rationale_basis = _choose_chart(query, context)
    insights = _summarize_with_llm(safe_client_id, query, chart_type, recharts_config, context)
 
    return {
        "agent": "BI Visualization Architect",
        "status": "COMPLETED",
        "recommended_chart_type": chart_type,
        "recharts_config": recharts_config,
        "data_preview": {
            "category_breakdown": context.get("category_breakdown", [])[:10],
            "monthly_totals": context.get("monthly_totals", [])[-12:],
            "unparseable_date_count": context.get("unparseable_date_count", 0),
        },
        "insights": insights or [f"Chart recommendation grounded in {rationale_basis}."]
    }