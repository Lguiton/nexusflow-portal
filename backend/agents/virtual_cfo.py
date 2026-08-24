import os
import json
import logging
import duckdb
from typing import Dict, Any
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

logger = logging.getLogger("nexusflow.virtual_cfo")

# AI-03: previously no explicit request timeout at all -- a hung OpenAI
# request had no client-side bound. max_retries matches the openai SDK's
# own default (2), made explicit here rather than left implicit.
AI_REQUEST_TIMEOUT_SECONDS = 30.0
AI_MAX_RETRIES = 2

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key, timeout=AI_REQUEST_TIMEOUT_SECONDS, max_retries=AI_MAX_RETRIES) if api_key else None

# Not sourced from any real data -- this system doesn't currently ingest a
# cash-balance figure. Cash runway is therefore an ASSUMED-reserve estimate,
# not a computed fact, for every tenant. Disclosed explicitly in the
# response below rather than silently presented as a real number.
ASSUMED_CASH_RESERVES = 1500000.0


def _empty_state_response() -> Dict[str, Any]:
    return {
        "status": "NO_DATA",
        "metrics": {
            "gross_margin": None,
            "burn_rate": None,
            "cash_runway_months": None
        },
        "insights": [
            "No ledger data has been ingested yet for this tenant. Upload a CSV ledger to generate your first executive briefing."
        ]
    }


def _error_state_response(reason: str) -> Dict[str, Any]:
    """
    FIXED (masked-failure bug, confirmed live 2026-08-22): distinct from
    _empty_state_response() above. This means the briefing could NOT be
    computed -- a real connection or query failure (e.g. contention on the
    shared DuckDB file from a concurrent ingest/read happening on another
    thread) -- not that this tenant genuinely has zero ledger rows.
    Previously ANY exception here (connection failure OR query failure)
    fell through to the exact same "No ledger data has been ingested yet"
    NO_DATA response as a real empty tenant, silently masking a transient
    failure as normal empty state. Confirmed live: generate_cfo_briefing
    called directly for a tenant with real rows returned this masked
    NO_DATA on the dashboard while a direct diagnostic call succeeded and
    returned real numbers -- proving this function's own math was correct
    and the dashboard failure was a masked connection race, not empty data.
    """
    return {
        "status": "ERROR",
        "metrics": {
            "gross_margin": None,
            "burn_rate": None,
            "cash_runway_months": None
        },
        "insights": [
            f"The CFO briefing could not be generated right now ({reason}). "
            "This is different from an empty tenant -- please retry; if it "
            "keeps happening, check the backend logs for the underlying error."
        ]
    }


def generate_cfo_briefing(client_id: str = "default_client") -> Dict[str, Any]:
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")

    total_revenue = 0.0
    total_cogs = 0.0
    total_opex = 0.0

    rows = []
    db_failed = False
    failure_reason = ""

    # FIXED: previously opened its own connection with NO synchronization
    # against db_manager.py's shared lock at all -- a live request here
    # could race a concurrent write/read from db_manager and get a
    # connection or query exception purely from that contention. Now
    # serialized through the SAME shared lock every other DB access in
    # this codebase uses, via db_manager.get_db_lock().
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
                        # Tenant-scoped only. Previously, if this returned no
                        # rows (a brand-new tenant with nothing uploaded
                        # yet), the code fell back to querying every
                        # tenant's ledger with no WHERE clause at all -- a
                        # real cross-tenant data leak. That fallback has
                        # been removed entirely: no rows for this tenant
                        # now means the honest empty-state response below,
                        # never another tenant's data.
                        rows = conn.execute(
                            "SELECT category, amount FROM ledgers WHERE client_id = ?",
                            [safe_client_id]
                        ).fetchall()
                except Exception as e:
                    logger.error(f"DuckDB query error in Virtual CFO: {e}")
                    db_failed = True
                    failure_reason = f"query failed: {e}"
                finally:
                    conn.close()

    # FIXED (masked-failure bug, confirmed live): a real connection/query
    # failure is no longer indistinguishable from a genuinely empty
    # tenant -- it now returns an explicit ERROR status instead of quietly
    # reusing the NO_DATA response.
    if db_failed:
        return _error_state_response(failure_reason)

    if not rows:
        return _empty_state_response()

    for cat, amt in rows:
        cat_lower = str(cat).lower()
        amt_float = float(amt) if amt is not None else 0.0

        if amt_float > 0:
            total_revenue += amt_float
        else:
            abs_amt = abs(amt_float)
            if any(k in cat_lower for k in ['hosting', 'aws', 'stripe', 'cogs', 'cost']):
                total_cogs += abs_amt
            else:
                total_opex += abs_amt

    # NOTE: revenue/COGS/OPEX classification here is a simple sign +
    # keyword heuristic, not a formally defined calculation -- your own
    # Master Build List (FIN-01/02/03) already tracks formal MRR/gross-
    # margin/cash-runway definitions and ground-truth tests as open items.
    # Not redesigning the formula here; that's a business-logic decision,
    # not a bug fix.
    gross_margin = 0.0
    if total_revenue > 0:
        gross_margin = ((total_revenue - total_cogs) / total_revenue) * 100

    burn_rate = total_cogs + total_opex
    cash_runway_months = (ASSUMED_CASH_RESERVES / burn_rate) if burn_rate > 0 else 99.9

    system_prompt = f"""
    You are NexusFlow's elite Virtual Chief Financial Officer (CFO).
    Tenant: {safe_client_id}.
    Calculated Metrics -> Revenue: ${total_revenue:,.2f}, COGS: ${total_cogs:,.2f}, OPEX: ${total_opex:,.2f}, Gross Margin: {gross_margin:.1f}%, Burn Rate: ${burn_rate:,.2f}, Runway: {cash_runway_months:.1f} months.
    IMPORTANT: the runway figure assumes a hypothetical ${ASSUMED_CASH_RESERVES:,.2f} cash reserve, not this tenant's actual bank balance (the system does not yet ingest real cash-balance data). Any insight referencing runway must state this is an estimate based on an assumed reserve, not a confirmed cash position.

    Generate EXACTLY 3 strategic executive insights based on these exact numbers.
    Respond in pure JSON:
    {{
      "metrics": {{
        "gross_margin": {gross_margin:.1f},
        "burn_rate": {burn_rate:.1f},
        "cash_runway_months": {cash_runway_months:.1f}
      }},
      "insights": [
        "Insight 1...",
        "Insight 2...",
        "Insight 3..."
      ]
    }}
    """

    try:
        if client:
            model = get_model("virtual_cfo")
            response = client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Generate executive briefing."}
                ],
                temperature=0.3
            )
            usage = getattr(response, "usage", None)
            if usage:
                log_ai_usage_sync(
                    safe_client_id, "virtual_cfo", model,
                    getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0), getattr(usage, "total_tokens", 0),
                    "SUCCESS"
                )
            result = json.loads(response.choices[0].message.content)
            metrics = result.get("metrics")
            insights = result.get("insights")
            # response_format guarantees valid JSON syntax, not the right
            # shape -- validate before trusting it, same fix as ops_shield.py.
            if (
                isinstance(metrics, dict)
                and all(k in metrics for k in ("gross_margin", "burn_rate", "cash_runway_months"))
                and isinstance(insights, list) and len(insights) > 0
            ):
                result["assumed_cash_reserves"] = ASSUMED_CASH_RESERVES
                return result
            logger.error(f"Unexpected CFO briefing response shape from LLM: {result!r}")
    except Exception as e:
        logger.error(f"OpenAI API error in CFO briefing: {e}")

    return {
        "metrics": {
            "gross_margin": round(gross_margin, 1),
            "burn_rate": round(burn_rate, 1),
            "cash_runway_months": round(cash_runway_months, 1)
        },
        "assumed_cash_reserves": ASSUMED_CASH_RESERVES,
        "insights": [
            f"Gross margin is operating at {gross_margin:.1f}%, reflecting current revenue-to-COGS efficiency.",
            f"Monthly burn rate is ${burn_rate:,.2f}, combining infrastructure and operating expenditures.",
            f"Estimated cash runway is {cash_runway_months:.1f} months, based on an assumed ${ASSUMED_CASH_RESERVES:,.2f} cash reserve (not yet sourced from real account data)."
        ]
    }