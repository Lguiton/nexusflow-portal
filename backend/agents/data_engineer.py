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

# Robust absolute path resolution for backend/.env
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

logger = logging.getLogger("nexusflow.data_engineer")


# AI-03: previously no explicit request timeout at all. max_retries matches
# the openai SDK's own default (2), made explicit here rather than left
# implicit.
AI_REQUEST_TIMEOUT_SECONDS = 30.0
AI_MAX_RETRIES = 2

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key, timeout=AI_REQUEST_TIMEOUT_SECONDS, max_retries=AI_MAX_RETRIES) if api_key else None


def _gather_schema_metrics(safe_client_id: str) -> Dict[str, Any]:
    """
    Real DuckDB introspection for this tenant. Previously
    analyze_schema_quality() had no data gathering at all -- the LLM was
    asked to "analyze" a schema it was never shown anything about.
    """
    metrics = {
        "table_exists": False,
        "total_rows": 0,
        "uncategorized_rows": 0,
        "default_description_rows": 0,
        "earliest_date": None,
        "latest_date": None,
        # FIXED (masked-failure bug, same class as virtual_cfo.py, confirmed
        # live 2026-08-22): a real connection/query exception used to leave
        # these defaults in place with no way to tell that apart from a
        # genuinely empty tenant. db_error/db_error_reason let callers
        # return an honest ERROR status instead of silently claiming
        # NO_DATA when the DB access itself failed.
        "db_error": False,
        "db_error_reason": "",
    }

    # FIXED: previously an unprotected, unsynchronized connection -- no
    # coordination at all with db_manager.py's shared lock, so a real
    # write/read happening concurrently elsewhere could raise here purely
    # from contention. Now serialized through the same shared lock.
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
                        metrics["table_exists"] = True
                        row = conn.execute(
                            """
                            SELECT
                                COUNT(*),
                                SUM(CASE WHEN category = 'Uncategorized' THEN 1 ELSE 0 END),
                                SUM(CASE WHEN description = 'Uploaded ledger entry' THEN 1 ELSE 0 END),
                                MIN(date),
                                MAX(date)
                            FROM ledgers WHERE client_id = ?
                            """,
                            [safe_client_id]
                        ).fetchone()
                        metrics["total_rows"] = row[0] or 0
                        metrics["uncategorized_rows"] = row[1] or 0
                        metrics["default_description_rows"] = row[2] or 0
                        metrics["earliest_date"] = row[3]
                        metrics["latest_date"] = row[4]
                except Exception as e:
                    logger.error(f"DuckDB query error in Data Engineer schema audit: {e}")
                    metrics["db_error"] = True
                    metrics["db_error_reason"] = f"query failed: {e}"
                finally:
                    conn.close()

    return metrics


def _template_recommendations(metrics: Dict[str, Any]) -> list:
    """Non-LLM fallback built directly from the real metrics above, so a
    failed/malformed LLM call still returns something honest rather than
    generic placeholder text."""
    recs = []
    total = metrics["total_rows"]
    if metrics["uncategorized_rows"]:
        pct = (metrics["uncategorized_rows"] / total * 100) if total else 0
        recs.append(
            f"{metrics['uncategorized_rows']} of {total} rows ({pct:.1f}%) are still marked "
            f"'Uncategorized' -- re-tagging these would improve BI/category-level reporting accuracy."
        )
    if metrics["default_description_rows"]:
        recs.append(
            f"{metrics['default_description_rows']} rows still carry the default "
            f"'Uploaded ledger entry' description -- consider requiring a real description on ingestion."
        )
    if metrics["earliest_date"] and metrics["latest_date"]:
        recs.append(
            f"Ledger data spans {metrics['earliest_date']} to {metrics['latest_date']} "
            f"across {total} row(s)."
        )
    if not recs:
        recs.append(f"{total} row(s) on file with no detected hygiene issues in the checks run.")
    return recs[:3]


def analyze_schema_quality(client_id: str = "default_client") -> Dict[str, Any]:
    """
    Agent #02 (Systems Analyst & Data Engineer).
    Analyzes the current DuckDB schema structure and pipeline integrity.
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    metrics = _gather_schema_metrics(safe_client_id)

    # FIXED (masked-failure bug, confirmed live): a real DB connection or
    # query failure is now reported as an explicit ERROR, distinct from a
    # tenant that genuinely has no ledger rows yet -- checked BEFORE the
    # NO_DATA branch below, since a failed lookup also leaves
    # table_exists/total_rows at their empty defaults.
    if metrics["db_error"]:
        return {
            "agent": "Systems Analyst Agent #02",
            "status": "ERROR",
            "recommendations": [
                f"The schema/data-hygiene audit could not run right now "
                f"({metrics['db_error_reason']}). This is different from an "
                "empty tenant -- please retry; if it keeps happening, check "
                "the backend logs for the underlying error."
            ]
        }

    if not metrics["table_exists"] or metrics["total_rows"] == 0:
        return {
            "agent": "Systems Analyst Agent #02",
            "status": "NO_DATA",
            "recommendations": [
                "No ledger data has been ingested yet for this tenant. Upload a CSV ledger to run a schema/data-hygiene audit."
            ]
        }

    system_prompt = f"""
    You are Agent #02, NexusFlow's Systems Analyst and Data Engineer.
    Tenant: {safe_client_id}.
    Real measured data for this tenant -> Total rows: {metrics['total_rows']}, Uncategorized rows: {metrics['uncategorized_rows']}, Rows with default description: {metrics['default_description_rows']}, Date range: {metrics['earliest_date']} to {metrics['latest_date']}.

    Base your recommendations ONLY on the real numbers above -- do not invent statistics or issues not reflected in this data.
    Provide exactly 3 automated recommendations for data hygiene, system optimization, or pipeline reliability.

    You MUST respond in pure JSON using this exact structure:
    {{
      "agent": "Systems Analyst Agent #02",
      "status": "OPTIMIZED",
      "recommendations": [
        "Recommendation 1...",
        "Recommendation 2...",
        "Recommendation 3..."
      ]
    }}
    """

    try:
        if not client:
            raise ValueError("OpenAI client not initialized (missing API key).")

        model = get_model("data_engineer")
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Run schema and pipeline health analysis."}
            ],
            temperature=0.3
        )
        usage = getattr(response, "usage", None)
        if usage:
            log_ai_usage_sync(
                safe_client_id, "data_engineer", model,
                getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0), getattr(usage, "total_tokens", 0),
                "SUCCESS"
            )
        result = json.loads(response.choices[0].message.content)
        recommendations = result.get("recommendations")
        # response_format guarantees valid JSON syntax, not the right shape --
        # validate before trusting it, same fix applied to ops_shield.py and
        # virtual_cfo.py.
        if isinstance(recommendations, list) and len(recommendations) > 0:
            result["metrics"] = metrics
            return result
        logger.error(f"Unexpected schema-audit response shape from LLM: {result!r}")
    except Exception as e:
        logger.error(f"Systems Analyst Agent Error: {e}")

    return {
        "agent": "Systems Analyst Agent #02",
        "status": "OPTIMIZED",
        "recommendations": _template_recommendations(metrics),
        "metrics": metrics
    }

# diagnose_and_propose_fix() intentionally removed -- it implemented an
# LLM-driven code-diff generator with no test-gate or branch-scoped-
# credential enforcement around it, contradicting the "no agent writes or
# executes code" decision repeated across every architecture document.
# Removed by explicit decision rather than left dormant, to match that
# formally-excluded status cleanly. Nothing else in the codebase called
# this function, so nothing else needs updating as a result.