import os
import json
import logging
import duckdb
from typing import Dict, Any, List
from dotenv import load_dotenv
from openai import OpenAI

try:
    from backend.db_manager import DB_PATH, get_db_lock, log_ai_usage_sync
    from backend.model_registry import get_model
except ImportError:
    from db_manager import DB_PATH, get_db_lock, log_ai_usage_sync
    from model_registry import get_model

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

logger = logging.getLogger("nexusflow.saas_strategist")


# AI-03: previously no explicit request timeout at all. max_retries matches
# the openai SDK's own default (2), made explicit here rather than left
# implicit.
AI_REQUEST_TIMEOUT_SECONDS = 30.0
AI_MAX_RETRIES = 2

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key, timeout=AI_REQUEST_TIMEOUT_SECONDS, max_retries=AI_MAX_RETRIES) if api_key else None


def _gather_strategic_metrics(safe_client_id: str) -> Dict[str, Any]:
    """
    Real, independent DuckDB query for this tenant -- same architectural
    pattern as every other agent file in this audit (each agent queries
    DB_PATH directly rather than importing another agent's function), so
    this stays consistent with virtual_cfo.py / bi_engineer.py /
    data_engineer.py / predictive_forecaster.py rather than introducing a
    new cross-agent dependency.
    """
    metrics: Dict[str, Any] = {
        "total_rows": 0,
        "total_revenue": 0.0,
        "top_categories": [],       # [{category, revenue, pct_of_total_revenue}]
        "monthly_revenue": [],      # [(period_label, revenue), ...] chronological
        "mom_change_pct": None,     # None if fewer than 2 distinct months on file
        # FIXED (masked-failure bug, same class confirmed live in
        # virtual_cfo.py 2026-08-22): lets the caller tell a real
        # connection/query failure apart from a genuinely empty tenant.
        "db_error": False,
        "db_error_reason": "",
    }

    # FIXED: previously an unprotected, unsynchronized connection -- now
    # serialized through db_manager.py's shared lock, same as every other
    # DB access in this codebase.
    if os.path.exists(DB_PATH):
        lock = get_db_lock()
        with lock:
            conn = None
            try:
                conn = duckdb.connect(DB_PATH, read_only=True)
            except Exception as e:
                logger.error(f"Failed to open DuckDB at {DB_PATH}: {e}")
                metrics["db_error"] = True
                metrics["db_error_reason"] = f"database connection failed: {e}"

            if conn:
                try:
                    tables = conn.execute("SHOW TABLES").fetchall()
                    table_names = [t[0] for t in tables]
                    if "ledgers" in table_names:
                        row = conn.execute(
                            """
                            SELECT COUNT(*), SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END)
                            FROM ledgers WHERE client_id = ?
                            """,
                            [safe_client_id]
                        ).fetchone()
                        metrics["total_rows"] = int(row[0] or 0)
                        metrics["total_revenue"] = float(row[1] or 0.0)

                        cat_rows = conn.execute(
                            """
                            SELECT category, SUM(amount) AS rev
                            FROM ledgers WHERE client_id = ? AND amount > 0
                            GROUP BY category ORDER BY rev DESC LIMIT 3
                            """,
                            [safe_client_id]
                        ).fetchall()
                        total_rev = metrics["total_revenue"]
                        for cat, rev in cat_rows:
                            rev_f = float(rev) if rev is not None else 0.0
                            pct = (rev_f / total_rev * 100) if total_rev else 0.0
                            metrics["top_categories"].append({
                                "category": str(cat),
                                "revenue": round(rev_f, 2),
                                "pct_of_total_revenue": round(pct, 1),
                            })

                        month_rows = conn.execute(
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
                        metrics["monthly_revenue"] = [(m, float(r)) for m, r in month_rows]

                        if len(metrics["monthly_revenue"]) >= 2:
                            prev_rev = metrics["monthly_revenue"][-2][1]
                            last_rev = metrics["monthly_revenue"][-1][1]
                            if prev_rev:
                                metrics["mom_change_pct"] = round((last_rev - prev_rev) / prev_rev * 100, 1)
                except Exception as e:
                    logger.error(f"DuckDB query error in SaaS Strategist: {e}")
                    metrics["db_error"] = True
                    metrics["db_error_reason"] = f"query failed: {e}"
                finally:
                    conn.close()

    return metrics


def _template_strategies(metrics: Dict[str, Any]) -> List[str]:
    """Non-LLM fallback built directly from the real metrics above -- same
    pattern as data_engineer.py's _template_recommendations(), so a failed
    or malformed LLM call still returns tenant-specific, honest content
    rather than the old generic boilerplate."""
    strategies = []

    if metrics["top_categories"]:
        top = metrics["top_categories"][0]
        strategies.append(
            f"{top['category']} accounts for {top['pct_of_total_revenue']}% of recorded revenue "
            f"(${top['revenue']:,.2f}) -- evaluate concentration risk and whether diversifying "
            f"revenue streams reduces exposure to this single category."
        )

    if metrics["mom_change_pct"] is not None:
        direction = "growing" if metrics["mom_change_pct"] >= 0 else "declining"
        strategies.append(
            f"Revenue is {direction} {abs(metrics['mom_change_pct']):.1f}% month-over-month based on "
            f"the two most recently recorded months -- confirm this holds for another cycle before "
            f"adjusting spend on the strength of it."
        )
    else:
        strategies.append(
            "Fewer than two distinct months of revenue history are on file, so no month-over-month "
            "trend can be computed yet -- continue ingesting ledger data to unlock trend-based strategy."
        )

    strategies.append(
        f"Total recorded revenue to date is ${metrics['total_revenue']:,.2f} across {metrics['total_rows']} "
        f"transaction(s) -- align pricing, packaging, and go-to-market spend to this actual transaction "
        f"volume rather than an assumed scale."
    )

    return strategies[:3]


def generate_strategy(client_id: str = "default_client") -> Dict[str, Any]:
    """
    Agent #10 (SaaS Strategist). Provides SaaS growth and operational
    strategy grounded in this tenant's real recorded revenue, category
    concentration, and month-over-month trend -- not generic,
    tenant-agnostic boilerplate.
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    metrics = _gather_strategic_metrics(safe_client_id)

    # FIXED (masked-failure bug, confirmed live): a real DB connection or
    # query failure is now reported as an explicit ERROR, distinct from a
    # tenant that genuinely has no ledger rows yet -- checked BEFORE the
    # NO_DATA branch below, since a failed lookup also leaves total_rows
    # at its empty default of 0.
    if metrics["db_error"]:
        return {
            "agent": "SaaS Strategist Agent #10",
            "status": "ERROR",
            "strategies": [
                f"The strategic advisory could not be generated right now "
                f"({metrics['db_error_reason']}). This is different from an "
                "empty tenant -- please retry; if it keeps happening, check "
                "the backend logs for the underlying error."
            ]
        }

    if metrics["total_rows"] == 0:
        return {
            "agent": "SaaS Strategist Agent #10",
            "status": "NO_DATA",
            "strategies": [
                "No ledger data has been ingested yet for this tenant. Upload a CSV ledger to generate a "
                "data-grounded strategic advisory."
            ]
        }

    top_cat_str = ", ".join(
        f"{c['category']} (${c['revenue']:,.2f}, {c['pct_of_total_revenue']}% of revenue)"
        for c in metrics["top_categories"]
    ) or "no category data available"

    trend_str = (
        f"{metrics['mom_change_pct']:+.1f}% month-over-month"
        if metrics["mom_change_pct"] is not None
        else "insufficient history to compute a month-over-month trend (fewer than 2 distinct months on file)"
    )

    system_prompt = f"""
    You are Agent #10, NexusFlow's SaaS Strategist and Business Advisor.
    Tenant: {safe_client_id}
    Real measured data -> Total revenue to date: ${metrics['total_revenue']:,.2f} across {metrics['total_rows']} ledger row(s). Top revenue categories: {top_cat_str}. Revenue trend: {trend_str}.

    Base your strategies ONLY on the real numbers above. Do not invent, imply, or reference any
    additional statistic, percentage, dollar figure, or trend not stated here. If the trend is
    reported as insufficient history, do not claim there is a growth or decline trend.

    Provide exactly 3 enterprise-grade SaaS growth and operational optimization strategies that
    reference these real numbers where relevant.

    You MUST respond in pure JSON using this exact structure:
    {{
      "agent": "SaaS Strategist Agent #10",
      "status": "OPTIMIZED",
      "strategies": [
        "Strategy 1...",
        "Strategy 2...",
        "Strategy 3..."
      ]
    }}
    """

    try:
        if not client:
            raise ValueError("OpenAI client not initialized.")

        model = get_model("saas_strategist")
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate strategic SaaS growth advisory."}
            ],
            temperature=0.3
        )
        usage = getattr(response, "usage", None)
        if usage:
            log_ai_usage_sync(
                safe_client_id, "saas_strategist", model,
                getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0), getattr(usage, "total_tokens", 0),
                "SUCCESS"
            )
        result = json.loads(response.choices[0].message.content)
        strategies = result.get("strategies")
        # response_format guarantees valid JSON syntax, not the right shape --
        # validate before trusting it, same fix applied to every other agent
        # file in this audit.
        if isinstance(strategies, list) and len(strategies) > 0:
            result["metrics"] = metrics
            return result
        logger.error(f"Unexpected SaaS strategy response shape from LLM: {result!r}")
    except Exception as e:
        logger.error(f"SaaS Strategist error: {e}")

    return {
        "agent": "SaaS Strategist Agent #10",
        "status": "FALLBACK",
        "strategies": _template_strategies(metrics),
        "metrics": metrics
    }
