import os
import json
import logging
import asyncio
import duckdb
from typing import Dict, Any, List, Optional, Tuple
from dotenv import load_dotenv
from openai import OpenAI

try:
    from backend.db_manager import DB_PATH, log_query_audit, get_db_lock, log_ai_usage_sync
    from backend.model_registry import get_model
except ImportError:
    from db_manager import DB_PATH, log_query_audit, get_db_lock, log_ai_usage_sync
    from model_registry import get_model

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)
logger = logging.getLogger("nexusflow.bi_engineer")

# AI-03: previously no explicit request timeout at all. max_retries matches
# the openai SDK's own default (2), made explicit here rather than left
# implicit.
AI_REQUEST_TIMEOUT_SECONDS = 30.0
AI_MAX_RETRIES = 2

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key, timeout=AI_REQUEST_TIMEOUT_SECONDS, max_retries=AI_MAX_RETRIES) if api_key else None


# ==============================================================================
# Data Analyst (#04) duties folded into BI Engineer (#05), per founder
# decision -- #04 itself was confirmed via git history to have never been a
# real implementation (a narration-only stub since the commit that created
# it). This section is the real thing: an ad hoc natural-language question
# gets translated into a CONSTRAINED structured "query intent", never into
# raw SQL text, then validated against a closed whitelist (SQL-01), then
# built into a real parameterized query entirely from code-authored SQL
# fragments (SQL-04's stated precondition for ever adding NL-to-SQL to this
# codebase). Every attempt is recorded via a SQL-03 audit trail
# (db_manager.log_query_audit), whether it succeeds, gets rejected by the
# whitelist, or never reaches the database at all.
#
# The LLM NEVER produces SQL syntax. It only ever selects KEYS from the
# dicts below -- the VALUES (the actual SQL fragments) are 100% authored in
# this file. There is no code path by which LLM-generated text becomes part
# of the executed SQL string; the only user/LLM-influenced content that
# reaches the database is a filter VALUE, and that is always bound as a
# parameterized `?` argument, never string-interpolated.
# ==============================================================================

_METRIC_SQL = {
    "total_amount": "SUM(amount)",
    "transaction_count": "COUNT(*)",
    "average_amount": "AVG(amount)",
    "min_amount": "MIN(amount)",
    "max_amount": "MAX(amount)",
    "earliest_date": "MIN(date)",
    "latest_date": "MAX(date)",
}
_ROW_COLUMN_SQL = {
    "date": "date",
    "category": "category",
    "amount": "amount",
    "description": "description",
}
_GROUP_BY_SQL = {
    "category": "category",
    # Same TRY_CAST/strftime month-bucketing pattern already established in
    # db_manager.get_ledger_chart_context -- an unparseable date is simply
    # excluded from its bucket rather than crashing the query.
    "month": "strftime(TRY_CAST(date AS DATE), '%Y-%m')",
}
# column -> (sql_expression, value_type). value_type drives how a filter's
# VALUE is coerced before it's ever bound as a query parameter.
_FILTER_COLUMN_SQL = {
    "category": ("category", "text"),
    "description": ("description", "text"),
    "amount": ("amount", "number"),
    "date": ("TRY_CAST(date AS DATE)", "date"),
}
_FILTER_OPS_SQL = {
    "=": "=", "!=": "!=", ">": ">", "<": "<", ">=": ">=", "<=": "<=",
    "contains": "LIKE",  # only valid on text-typed columns -- enforced in _validate_intent
}
_MAX_ROW_LIMIT = 500
_DEFAULT_ROW_LIMIT = 50


def _safe_limit(value: Any) -> int:
    """Same clamping discipline as db_manager._safe_window -- coerce and
    bound, never trust a raw LLM-supplied number directly into a query."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = _DEFAULT_ROW_LIMIT
    return max(1, min(n, _MAX_ROW_LIMIT))


def _in_running_loop() -> bool:
    """Same explicit check used in orchestrator.py/bi_visualization_architect.py
    -- avoids a bare `except RuntimeError` mislabeling an unrelated failure
    as a nested-event-loop issue."""
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def _sync_log_query_audit(client_id: str, natural_language_query: str, generated_query: str, row_count: int, status: str):
    if _in_running_loop():
        logger.warning("BI Engineer: query audit log skipped -- already inside a running event loop.")
        return
    try:
        asyncio.run(log_query_audit(client_id, natural_language_query, generated_query, row_count, status))
    except Exception as e:
        logger.error(f"BI Engineer: failed to write query audit log: {e}")


def _ask_llm_for_query_intent(client_id: str, query: str) -> Optional[dict]:
    """
    Translates a natural-language question into a structured intent. The
    LLM never writes SQL -- it only picks keys from the fixed vocabularies
    below. Returns None if no LLM is configured or the call/parse fails
    outright; the returned shape is validated separately by
    _validate_intent, which does not trust this function's output either.
    """
    if not client:
        return None
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    system_prompt = f"""
    You are translating a natural-language question about tenant {safe_client_id}'s
    financial ledger into a STRICT structured query intent. You do NOT write SQL --
    you only select from these fixed vocabularies, and you must never invent a
    key, column, or operator outside them:

    Aggregate metrics (mode="aggregate" select values): {list(_METRIC_SQL.keys())}
    Row columns (mode="rows" select values): {list(_ROW_COLUMN_SQL.keys())}
    Group-by keys (mode="aggregate" only): {list(_GROUP_BY_SQL.keys())}
    Filter columns: {list(_FILTER_COLUMN_SQL.keys())}
    Filter operators: {list(_FILTER_OPS_SQL.keys())} ("contains" only valid for category/description)

    Question: {query}

    Use mode="aggregate" for totals/breakdowns/summaries. Use mode="rows" to
    list individual transactions. There is no "client_id" or tenant field --
    every query is already scoped to this tenant automatically; never
    attempt to reference or filter on client_id yourself.

    Respond STRICTLY in JSON with this exact shape:
    {{
      "mode": "aggregate" or "rows",
      "select": ["..."],
      "group_by": ["..."],
      "filters": [{{"column": "...", "op": "...", "value": "..."}}],
      "order_by": {{"column": "...", "direction": "ASC"}} or null,
      "limit": 50
    }}
    """
    try:
        model = get_model("bi_engineer_query_intent")
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.1,
        )
        usage = getattr(response, "usage", None)
        if usage:
            log_ai_usage_sync(
                safe_client_id, "bi_engineer", model,
                getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0), getattr(usage, "total_tokens", 0),
                "SUCCESS"
            )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.warning(f"BI Engineer: query intent generation failed for {safe_client_id}: {e}")
        return None


def _validate_intent(raw_intent: Any) -> Tuple[Optional[dict], str]:
    """
    SQL-01 enforcement point. Strips or rejects anything not in the fixed
    whitelists above -- never trusts the LLM's shape or content, including
    any attempt (deliberate or accidental) to reference client_id, an
    unlisted column, or an unlisted operator. Returns
    (cleaned_intent_or_None, reason); cleaned_intent is None if nothing
    usable survived validation.
    """
    if not isinstance(raw_intent, dict):
        return None, "Query intent was not a JSON object."

    mode = raw_intent.get("mode")
    if mode not in ("aggregate", "rows"):
        return None, f"Unrecognized mode {mode!r}."

    select_vocab = _METRIC_SQL if mode == "aggregate" else _ROW_COLUMN_SQL
    raw_select = raw_intent.get("select")
    select = [s for s in raw_select if isinstance(s, str) and s in select_vocab] if isinstance(raw_select, list) else []
    if not select:
        return None, f"No valid '{mode}' select fields survived validation."

    group_by: List[str] = []
    if mode == "aggregate":
        raw_group_by = raw_intent.get("group_by")
        if isinstance(raw_group_by, list):
            group_by = [g for g in raw_group_by if isinstance(g, str) and g in _GROUP_BY_SQL]

    filters: List[dict] = []
    raw_filters = raw_intent.get("filters")
    if isinstance(raw_filters, list):
        for f in raw_filters:
            if not isinstance(f, dict):
                continue
            col = f.get("column")
            op = f.get("op")
            val = f.get("value")
            if col not in _FILTER_COLUMN_SQL or op not in _FILTER_OPS_SQL:
                continue  # unlisted column/op (e.g. a "client_id" filter attempt) -- silently dropped
            _, value_type = _FILTER_COLUMN_SQL[col]
            if op == "contains" and value_type != "text":
                continue  # "contains" only valid on text columns
            if value_type == "number":
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    continue  # unparseable numeric filter value -- drop this filter, don't crash
            elif val is None:
                continue
            else:
                val = str(val)
            filters.append({"column": col, "op": op, "value": val})

    valid_order_targets = set(select) | set(group_by)
    order_by = None
    raw_order_by = raw_intent.get("order_by")
    if isinstance(raw_order_by, dict):
        ob_col = raw_order_by.get("column")
        ob_dir = raw_order_by.get("direction")
        if ob_col in valid_order_targets and ob_dir in ("ASC", "DESC"):
            order_by = {"column": ob_col, "direction": ob_dir}

    limit = _safe_limit(raw_intent.get("limit"))

    return {
        "mode": mode,
        "select": select,
        "group_by": group_by,
        "filters": filters,
        "order_by": order_by,
        "limit": limit,
    }, "OK"


def _build_sql_from_intent(intent: dict, client_id: str) -> Tuple[str, list]:
    """
    Builds the actual parameterized SQL from a VALIDATED intent only.
    Every fragment of SQL text here comes from the code-authored dicts
    above, keyed by strings that already passed _validate_intent -- this
    function trusts that gate completely and performs no further
    string-safety checks of its own. client_id is always injected HERE,
    never read from the intent, and is always the first bound parameter
    and the first WHERE clause -- there is no way for a query this
    function builds to omit tenant scoping or scope to a different tenant.
    """
    mode = intent["mode"]
    vocab = _METRIC_SQL if mode == "aggregate" else _ROW_COLUMN_SQL
    select_exprs = [f"{vocab[key]} AS {key}" for key in intent["select"]]

    group_by_exprs = []
    if mode == "aggregate":
        for key in intent["group_by"]:
            group_by_exprs.append(_GROUP_BY_SQL[key])
            alias_expr = f"{_GROUP_BY_SQL[key]} AS {key}"
            # A grouping dimension the LLM forgot to also select is added
            # to the output anyway -- a "total by category" answer with no
            # category label attached isn't useful.
            if alias_expr not in select_exprs:
                select_exprs.insert(0, alias_expr)

    params: list = [client_id]
    where_clauses = ["client_id = ?"]
    for f in intent["filters"]:
        sql_col, _ = _FILTER_COLUMN_SQL[f["column"]]
        sql_op = _FILTER_OPS_SQL[f["op"]]
        if sql_op == "LIKE":
            where_clauses.append(f"{sql_col} LIKE ?")
            params.append(f"%{f['value']}%")
        elif f["column"] == "date":
            where_clauses.append(f"{sql_col} {sql_op} TRY_CAST(? AS DATE)")
            params.append(f["value"])
        else:
            where_clauses.append(f"{sql_col} {sql_op} ?")
            params.append(f["value"])

    sql = f"SELECT {', '.join(select_exprs)} FROM ledgers WHERE {' AND '.join(where_clauses)}"
    if group_by_exprs:
        sql += f" GROUP BY {', '.join(group_by_exprs)}"
    if intent["order_by"]:
        sql += f" ORDER BY {intent['order_by']['column']} {intent['order_by']['direction']}"
    # limit was already coerced to an int and clamped to [1, 500] by
    # _safe_limit inside _validate_intent -- unlike every data VALUE above
    # (always bound as a `?` parameter), embedding this validated integer
    # directly is safe because it is guaranteed to be a Python int within a
    # fixed range by the time it ever touches this string.
    sql += f" LIMIT {intent['limit']}"
    return sql, params


def _answer_data_question(client_id: str, query: str) -> Dict[str, Any]:
    """
    Top-level entry point for the folded-in Data Analyst duties. Every
    attempt -- success, whitelist rejection, LLM failure, or execution
    error -- is recorded via the SQL-03 audit trail before returning.
    """
    if not query or not query.strip():
        return {"status": "NO_QUESTION_ASKED"}

    raw_intent = _ask_llm_for_query_intent(client_id, query)
    if raw_intent is None:
        _sync_log_query_audit(client_id, query, "N/A", 0, "LLM_UNAVAILABLE_OR_FAILED")
        return {"status": "COULD_NOT_ANSWER", "reason": "Query understanding is unavailable right now."}

    intent, reason = _validate_intent(raw_intent)
    if intent is None:
        _sync_log_query_audit(client_id, query, f"REJECTED: {reason}", 0, "REJECTED_BY_WHITELIST")
        return {"status": "COULD_NOT_ANSWER", "reason": reason}

    sql, params = _build_sql_from_intent(intent, client_id)

    # FIXED: this connection was previously unsynchronized with
    # db_manager.py's shared lock -- now serialized through the same lock
    # every other DB access in this codebase uses, so a real write/read
    # happening concurrently elsewhere can't raise a spurious execution
    # error here purely from contention.
    lock = get_db_lock()
    try:
        with lock:
            conn = duckdb.connect(DB_PATH, read_only=True)
            try:
                result = conn.execute(sql, params)
                columns = [d[0] for d in result.description]
                rows = result.fetchall()
            finally:
                conn.close()
    except Exception as e:
        logger.error(f"BI Engineer: query execution failed for {client_id}: {e}")
        _sync_log_query_audit(client_id, query, sql, 0, "EXECUTION_ERROR")
        return {"status": "COULD_NOT_ANSWER", "reason": "The generated query failed to execute."}

    row_dicts = [dict(zip(columns, r)) for r in rows]
    _sync_log_query_audit(client_id, query, sql, len(rows), "SUCCESS")
    return {
        "status": "ANSWERED",
        "columns": columns,
        "rows": row_dicts,
        "row_count": len(rows),
    }


def _empty_state_response() -> Dict[str, Any]:
    return {
        "agent": "BI Engineer Agent #05",
        "status": "NO_DATA",
        "total_records": 0,
        "category_distribution": {},
        "insights": [
            "No ledger data has been ingested yet for this tenant. Upload a CSV ledger to generate a BI summary."
        ]
    }


def _error_state_response(reason: str) -> Dict[str, Any]:
    """
    FIXED (masked-failure bug, same class confirmed live in virtual_cfo.py
    2026-08-22): distinct from _empty_state_response() -- this means the BI
    summary could NOT be computed (a real connection/query failure), not
    that the tenant genuinely has zero ledger rows.
    """
    return {
        "agent": "BI Engineer Agent #05",
        "status": "ERROR",
        "total_records": 0,
        "category_distribution": {},
        "insights": [
            f"The BI summary could not be generated right now ({reason}). "
            "This is different from an empty tenant -- please retry; if it "
            "keeps happening, check the backend logs for the underlying error."
        ]
    }


def _template_insights(category_breakdown: Dict[str, Any], total_records: int) -> List[str]:
    """Non-LLM fallback built directly from the real computed
    category_breakdown/total_records, so a failed/malformed LLM call still
    returns something honest and specific to this tenant's actual data,
    instead of generic canned text (e.g. "Primary revenue concentration
    remains heavily tied to core sales categories") that could easily be
    wrong for a given tenant's real numbers. Mirrors the same fallback
    discipline already used in data_engineer.py's _template_recommendations."""
    if not category_breakdown:
        return [f"{total_records} record(s) on file; no categorical breakdown available."]

    sorted_cats = sorted(category_breakdown.items(), key=lambda kv: kv[1]["sum"], reverse=True)
    insights: List[str] = []

    top_cat, top_data = sorted_cats[0]
    insights.append(
        f"'{top_cat}' is the largest category by amount (${top_data['sum']:,.2f} across "
        f"{top_data['count']} transaction(s))."
    )

    if len(sorted_cats) > 1:
        cost_like = [(c, d) for c, d in sorted_cats if d["sum"] < 0]
        if cost_like:
            biggest_cost, biggest_cost_data = max(cost_like, key=lambda cd: abs(cd[1]["sum"]))
            insights.append(
                f"'{biggest_cost}' is the largest cost driver at ${abs(biggest_cost_data['sum']):,.2f}."
            )
        else:
            insights.append(
                f"{len(sorted_cats)} categories are tracked across {total_records} total record(s), "
                f"all net-positive."
            )
    else:
        insights.append(f"All {total_records} record(s) fall under the single category '{top_cat}'.")

    plural = "y" if len(sorted_cats) == 1 else "ies"
    insights.append(
        f"{total_records} total ledger record(s) processed across {len(sorted_cats)} categor{plural}."
    )

    return insights[:3]


def generate_bi_summary(client_id: str = "default_client", query: str = "") -> Dict[str, Any]:
    """
    Agent #05 (BI Engineer). Two things happen here now:
    (1) the original categorical-breakdown summary (unchanged from before),
    and (2) if `query` is a real question, a genuine attempt to answer it
    via _answer_data_question above -- the Data Analyst (#04) duties folded
    into this agent per founder decision, now that #04 was confirmed (via
    git history) to have never been a real implementation.

    Note on cost: this now makes a second LLM call (query-intent
    translation) on every invocation where `query` is non-empty, even a
    generic routed query that isn't really an ad hoc data question --
    _answer_data_question degrades gracefully to COULD_NOT_ANSWER in that
    case, but the LLM call still happens. Worth knowing this has a real
    per-call cost implication now.
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    category_breakdown = {}
    total_records = 0
    db_failed = False
    failure_reason = ""

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
                db_failed = True
                failure_reason = f"database connection failed: {e}"

            if conn:
                try:
                    tables = conn.execute("SHOW TABLES").fetchall()
                    table_names = [t[0] for t in tables]
                    if "ledgers" in table_names:
                        # Tenant-scoped only -- the previous fallback to an
                        # unfiltered GROUP BY (when this tenant had no rows)
                        # mixed every tenant's data into what was presented
                        # as one tenant's BI summary. Removed; no rows now
                        # means the honest empty-state response below.
                        rows = conn.execute(
                            "SELECT category, COUNT(*), SUM(amount) FROM ledgers WHERE client_id = ? GROUP BY category",
                            [safe_client_id]
                        ).fetchall()
                        for cat, count, total_amt in rows:
                            category_breakdown[str(cat)] = {
                                "count": int(count),
                                "sum": float(total_amt) if total_amt is not None else 0.0
                            }
                            total_records += int(count)
                except Exception as e:
                    logger.error(f"DuckDB query error in BI Engineer: {e}")
                    db_failed = True
                    failure_reason = f"query failed: {e}"
                finally:
                    conn.close()

    # FIXED (masked-failure bug, confirmed live): a real connection/query
    # failure is no longer indistinguishable from a genuinely empty
    # tenant -- checked BEFORE the NO_DATA branch below.
    if db_failed:
        return _error_state_response(failure_reason)

    if not category_breakdown:
        return _empty_state_response()

    query_answer = _answer_data_question(safe_client_id, query)

    query_context_block = ""
    if query_answer.get("status") == "ANSWERED":
        query_context_block = f"""
    An ad hoc question was also asked and answered for real (not invented):
    "{query}" -> {json.dumps(query_answer)}
    Ground any relevant insight in this real answer -- do not restate the
    numbers differently than shown."""

    system_prompt = f"""
    You are Agent #05, NexusFlow's Business Intelligence Engineer.
    Tenant: {safe_client_id}
    Categorical Data Summary: {json.dumps(category_breakdown)}
    Total Ledger Records: {total_records}
    {query_context_block}
    Provide exactly 3 executive BI insights focusing on categorical distribution, revenue concentration, and cost drivers.
    Respond STRICTLY in JSON: {{"insights": ["...", "...", "..."]}}
    """
    try:
        if not client:
            raise ValueError("OpenAI client not initialized.")
        model = get_model("bi_engineer_distribution")
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate BI statistical distribution analysis."}
            ],
            temperature=0.3
        )
        usage = getattr(response, "usage", None)
        if usage:
            log_ai_usage_sync(
                safe_client_id, "bi_engineer", model,
                getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0), getattr(usage, "total_tokens", 0),
                "SUCCESS"
            )
        result = json.loads(response.choices[0].message.content)
        insights = result.get("insights")
        # response_format guarantees valid JSON syntax, not the right shape --
        # validate before trusting it, same fix as the last three agent files.
        #
        # The final response is assembled from the LOCALLY computed
        # category_breakdown/total_records, never from result's echoed
        # copies of them -- an LLM is not a reliable place to round-trip
        # figures already computed for real; only its "insights" commentary
        # is genuinely its own contribution.
        if isinstance(insights, list) and len(insights) > 0:
            return {
                "agent": "BI Engineer Agent #05",
                "status": "OPTIMIZED",
                "total_records": total_records,
                "category_distribution": category_breakdown,
                "query_answer": query_answer,
                "insights": [str(i) for i in insights]
            }
        logger.error(f"Unexpected BI summary response shape from LLM: {result!r}")
    except Exception as e:
        logger.error(f"BI Engineer error: {e}")

    return {
        "agent": "BI Engineer Agent #05",
        "status": "FALLBACK",
        "total_records": total_records,
        "category_distribution": category_breakdown,
        "query_answer": query_answer,
        "insights": _template_insights(category_breakdown, total_records)
    }
