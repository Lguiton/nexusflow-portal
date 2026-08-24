import os
import json
import logging
import duckdb
from typing import Dict, Any, Optional, Tuple
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

logger = logging.getLogger("nexusflow.report_generator")


# AI-03: previously no explicit request timeout at all. max_retries matches
# the openai SDK's own default (2), made explicit here rather than left
# implicit.
AI_REQUEST_TIMEOUT_SECONDS = 30.0
AI_MAX_RETRIES = 2

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key, timeout=AI_REQUEST_TIMEOUT_SECONDS, max_retries=AI_MAX_RETRIES) if api_key else None


def _empty_state_response() -> Dict[str, Any]:
    return {
        "agent": "Report Generator Agent #06",
        "status": "NO_DATA",
        "summary_metrics": {
            "total_revenue": 0.0,
            "total_expenses": 0.0,
            "net_income": 0.0,
            "records_audited": 0
        },
        "executive_sections": [
            {
                "title": "No Data Available",
                "summary": "No ledger data has been ingested yet for this tenant. Upload a CSV ledger to generate a stakeholder report."
            }
        ]
    }


def _error_state_response(reason: str) -> Dict[str, Any]:
    """
    FIXED (same masked-failure bug found and fixed this update in
    virtual_cfo.py, data_engineer.py, bi_engineer.py, and saas_strategist.py
    -- report_generator.py had the identical pattern and was missed in that
    pass). Distinct from _empty_state_response() above: this means the
    report could NOT be computed -- a real connection or query failure --
    not that this tenant genuinely has zero ledger rows.
    """
    return {
        "agent": "Report Generator Agent #06",
        "status": "ERROR",
        "summary_metrics": {
            "total_revenue": None,
            "total_expenses": None,
            "net_income": None,
            "records_audited": None
        },
        "executive_sections": [
            {
                "title": "Report Unavailable",
                "summary": (
                    f"The stakeholder report could not be generated right now ({reason}). "
                    "This is different from an empty tenant -- please retry; if it keeps "
                    "happening, check the backend logs for the underlying error."
                )
            }
        ]
    }


def _validate_report_shape(result: Dict[str, Any]) -> bool:
    """response_format guarantees valid JSON syntax, not the right shape --
    check both the metrics dict and the sections list actually match the
    contract before this goes out to a real stakeholder. This audience --
    per your own framing -- is investors, board members, and SMB owners
    without in-house data science/BI staff to catch a malformed or
    fabricated report themselves, so this validation matters more here
    than in any other agent file."""
    metrics = result.get("summary_metrics")
    sections = result.get("executive_sections")
    if not isinstance(metrics, dict):
        return False
    if not all(k in metrics for k in ("total_revenue", "total_expenses", "net_income", "records_audited")):
        return False
    if not isinstance(sections, list) or len(sections) == 0:
        return False
    for s in sections:
        if not isinstance(s, dict) or "title" not in s or "summary" not in s:
            return False
    return True


def _gather_report_metrics(safe_client_id: str) -> Tuple[Dict[str, Any], bool, str]:
    """
    Real, independent DuckDB query for this tenant -- same architectural
    pattern as every other agent file in this audit (each agent queries
    DB_PATH directly rather than importing another agent's function).

    FIXED: previously opened its own connection with NO synchronization
    against db_manager.py's shared lock at all, and any exception here
    (connection failure OR query failure) was silently indistinguishable
    from a genuinely empty tenant -- same masked-failure pattern already
    fixed in virtual_cfo.py/data_engineer.py/bi_engineer.py/saas_strategist.py.
    Now serialized through the same shared lock via db_manager.get_db_lock(),
    and returns (metrics, db_failed, failure_reason) so the caller can tell
    a real failure apart from a real empty result.

    Extends the original 3 raw totals with two more real, unassumed
    figures: top revenue category concentration (same query shape as
    bi_engineer.py / saas_strategist.py) and month-over-month revenue
    trend (same query shape as predictive_forecaster.py /
    saas_strategist.py). Deliberately does NOT include Virtual CFO's
    margin/burn/runway -- runway is built on an assumed, not measured,
    cash reserve (FIN-03 still open), and this report's audience
    (investors, stakeholders, SMB owners without in-house data teams)
    can't independently sanity-check a placeholder number the way an
    internal team could. Confirmed with you directly to exclude it here.
    """
    metrics: Dict[str, Any] = {
        "total_revenue": 0.0,
        "total_expenses": 0.0,
        "net_income": 0.0,
        "record_count": 0,
        "top_category": None,       # {category, revenue, pct_of_total_revenue} or None
        "monthly_revenue": [],      # [(period_label, revenue), ...] chronological
        "mom_change_pct": None,     # None if fewer than 2 distinct months on file
    }
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
                        # All queries below are tenant-scoped with WHERE client_id = ? --
                        # no cross-tenant leak in this file, unchanged from the last version.
                        rev_res = conn.execute(
                            "SELECT SUM(amount) FROM ledgers WHERE client_id = ? AND amount > 0",
                            [safe_client_id]
                        ).fetchone()
                        metrics["total_revenue"] = float(rev_res[0]) if rev_res and rev_res[0] is not None else 0.0

                        exp_res = conn.execute(
                            "SELECT SUM(ABS(amount)) FROM ledgers WHERE client_id = ? AND amount < 0",
                            [safe_client_id]
                        ).fetchone()
                        metrics["total_expenses"] = float(exp_res[0]) if exp_res and exp_res[0] is not None else 0.0

                        count_res = conn.execute(
                            "SELECT COUNT(*) FROM ledgers WHERE client_id = ?",
                            [safe_client_id]
                        ).fetchone()
                        metrics["record_count"] = int(count_res[0]) if count_res and count_res[0] is not None else 0

                        cat_row = conn.execute(
                            """
                            SELECT category, SUM(amount) AS rev
                            FROM ledgers WHERE client_id = ? AND amount > 0
                            GROUP BY category ORDER BY rev DESC LIMIT 1
                            """,
                            [safe_client_id]
                        ).fetchone()
                        if cat_row and cat_row[0] is not None:
                            cat_rev = float(cat_row[1]) if cat_row[1] is not None else 0.0
                            pct = (cat_rev / metrics["total_revenue"] * 100) if metrics["total_revenue"] else 0.0
                            metrics["top_category"] = {
                                "category": str(cat_row[0]),
                                "revenue": round(cat_rev, 2),
                                "pct_of_total_revenue": round(pct, 1),
                            }

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
                    logger.error(f"DuckDB query error in Report Generator: {e}")
                    db_failed = True
                    failure_reason = f"query failed: {e}"
                finally:
                    conn.close()

    return metrics, db_failed, failure_reason


def _template_sections(metrics: Dict[str, Any], net_income: float) -> list:
    """Non-LLM fallback built directly from the real metrics above -- same
    pattern as data_engineer.py / saas_strategist.py, so a failed or
    malformed LLM call still returns real, tenant-specific content."""
    total_revenue = metrics["total_revenue"]
    total_expenses = metrics["total_expenses"]
    record_count = metrics["record_count"]

    revenue_summary = f"Audited ledger reflects ${total_revenue:,.2f} in gross transactional inflows across {record_count} recorded transaction(s)."
    if metrics["top_category"]:
        tc = metrics["top_category"]
        revenue_summary = (
            f"Audited ledger reflects ${total_revenue:,.2f} in gross transactional inflows across "
            f"{record_count} recorded transaction(s). {tc['category']} is the largest contributor at "
            f"${tc['revenue']:,.2f} ({tc['pct_of_total_revenue']}% of recorded revenue)."
        )

    expense_summary = f"Cumulative recorded outflows total ${total_expenses:,.2f}, resulting in a net position of ${net_income:,.2f}."

    if metrics["mom_change_pct"] is not None:
        direction = "grew" if metrics["mom_change_pct"] >= 0 else "declined"
        strategic_summary = (
            f"Revenue {direction} {abs(metrics['mom_change_pct']):.1f}% month-over-month based on the two "
            f"most recently recorded months. Net position is currently "
            f"{'positive' if net_income >= 0 else 'negative'} at ${net_income:,.2f}."
        )
    else:
        strategic_summary = (
            f"Fewer than two distinct months of revenue history are on file, so no month-over-month trend "
            f"can be reported yet. Net position is currently {'positive' if net_income >= 0 else 'negative'} "
            f"at ${net_income:,.2f} -- "
            + (
                "continue monitoring expense growth relative to revenue."
                if net_income >= 0
                else "recorded expenses currently exceed recorded revenue and warrant review."
            )
        )

    return [
        {"title": "Revenue Realization", "summary": revenue_summary},
        {"title": "Expense Governance", "summary": expense_summary},
        {"title": "Strategic Recommendation", "summary": strategic_summary},
    ]


def generate_stakeholder_report(client_id: str = "default_client") -> Dict[str, Any]:
    """
    Agent #06 (Report Generator). Synthesizes real per-tenant ledger data --
    revenue, expenses, net income, category concentration, and
    month-over-month trend -- into a stakeholder-facing report. Built for
    an audience (investors, board members, SMB owners) who may not have
    in-house data science/BI staff to independently verify a number, so
    every figure here is either a direct query result or a number derived
    from one; nothing is invented, and no assumed/placeholder figures
    (e.g. Virtual CFO's assumed-cash-reserve runway) are included.
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    metrics, db_failed, failure_reason = _gather_report_metrics(safe_client_id)

    # FIXED (masked-failure bug): a real connection/query failure is no
    # longer indistinguishable from a genuinely empty tenant.
    if db_failed:
        return _error_state_response(failure_reason)

    if metrics["record_count"] == 0:
        # Previously this fell through to the LLM anyway with every figure
        # at zero, and asked it to "synthesize an executive stakeholder
        # debrief" over nothing -- risking a fabricated-sounding report
        # about a tenant with no data at all.
        return _empty_state_response()

    net_income = metrics["total_revenue"] - metrics["total_expenses"]

    top_cat_str = (
        f"{metrics['top_category']['category']} (${metrics['top_category']['revenue']:,.2f}, "
        f"{metrics['top_category']['pct_of_total_revenue']}% of revenue)"
        if metrics["top_category"] else "no category data available"
    )
    trend_str = (
        f"{metrics['mom_change_pct']:+.1f}% month-over-month"
        if metrics["mom_change_pct"] is not None
        else "insufficient history to compute a month-over-month trend (fewer than 2 distinct months on file)"
    )

    system_prompt = f"""
    You are Agent #06, NexusFlow's Report Generator.
    Tenant: {safe_client_id}
    Real measured ledger data -> Total Revenue: ${metrics['total_revenue']:,.2f}, Total Outflows: ${metrics['total_expenses']:,.2f}, Net Position: ${net_income:,.2f}, Ingested Records: {metrics['record_count']}. Top revenue category: {top_cat_str}. Revenue trend: {trend_str}.

    IMPORTANT: this audience includes investors, board members, and SMB owners who may not have in-house
    data scientists or analysts to catch a wrong or invented number themselves. The figures above are the
    ONLY real data you have. Do not invent, imply, or reference any additional statistic, percentage,
    category, cash balance, cash runway, burn rate, or gross margin -- none of those are measured in this
    report. If the trend is reported as insufficient history, do not claim there is a growth or decline
    trend.

    Synthesize an executive stakeholder debrief covering revenue realization, expense governance, and a
    strategic recommendation, using ONLY the real numbers above.

    You MUST respond in pure JSON using this exact structure:
    {{
      "agent": "Report Generator Agent #06",
      "status": "GENERATED",
      "summary_metrics": {{
        "total_revenue": {metrics['total_revenue']},
        "total_expenses": {metrics['total_expenses']},
        "net_income": {net_income},
        "records_audited": {metrics['record_count']}
      }},
      "executive_sections": [
        {{ "title": "Revenue Realization", "summary": "Analysis content..." }},
        {{ "title": "Expense Governance", "summary": "Analysis content..." }},
        {{ "title": "Strategic Recommendation", "summary": "Analysis content..." }}
      ]
    }}
    """

    try:
        if not client:
            raise ValueError("OpenAI client not initialized.")

        model = get_model("report_generator")
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate executive stakeholder governance report."}
            ],
            temperature=0.2
        )
        usage = getattr(response, "usage", None)
        if usage:
            log_ai_usage_sync(
                safe_client_id, "report_generator", model,
                getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0), getattr(usage, "total_tokens", 0),
                "SUCCESS"
            )
        result = json.loads(response.choices[0].message.content)
        # response_format guarantees valid JSON syntax, not the right shape --
        # validate before trusting it, same fix applied to every other agent
        # file in this audit.
        if _validate_report_shape(result):
            result["summary_metrics"]["top_category"] = metrics["top_category"]
            result["summary_metrics"]["revenue_trend_pct"] = metrics["mom_change_pct"]
            return result
        logger.error(f"Unexpected stakeholder report response shape from LLM: {result!r}")
    except Exception as e:
        logger.error(f"Report Generator API error: {e}")

    return {
        "agent": "Report Generator Agent #06",
        "status": "FALLBACK",
        "summary_metrics": {
            "total_revenue": metrics["total_revenue"],
            "total_expenses": metrics["total_expenses"],
            "net_income": net_income,
            "records_audited": metrics["record_count"],
            "top_category": metrics["top_category"],
            "revenue_trend_pct": metrics["mom_change_pct"],
        },
        "executive_sections": _template_sections(metrics, net_income)
    }
