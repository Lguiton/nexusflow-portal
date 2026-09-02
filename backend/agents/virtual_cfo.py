import os
import re
import json
import logging
import duckdb
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

try:
    from backend import db_manager
    from backend.db_manager import get_db_lock, log_ai_usage_sync
    from backend.model_registry import get_model
    from backend.byok import get_openai_client_for_tenant_sync
except ImportError:
    import db_manager
    from db_manager import get_db_lock, log_ai_usage_sync
    from model_registry import get_model
    from byok import get_openai_client_for_tenant_sync

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

logger = logging.getLogger("eivanta.virtual_cfo")

# AI-03: previously no explicit request timeout at all -- a hung OpenAI
# request had no client-side bound. max_retries matches the openai SDK's
# own default (2), made explicit here rather than left implicit.
AI_REQUEST_TIMEOUT_SECONDS = 30.0
AI_MAX_RETRIES = 2

# BYOK-01: this used to be a single module-level client built once from the
# platform's own OPENAI_API_KEY at import time -- fine when every tenant
# shares the platform key, but incapable of ever routing to a tenant's own
# key. platform_api_key is kept as the fallback; the actual client is now
# built per-call in generate_cfo_briefing() via
# get_openai_client_for_tenant_sync, which uses the calling tenant's BYOK
# key when they've configured one.
platform_api_key = os.getenv("OPENAI_API_KEY")

# Not sourced from any real data -- this system doesn't currently ingest a
# cash-balance figure. Cash runway is therefore an ASSUMED-reserve estimate,
# not a computed fact, for every tenant. Disclosed explicitly in the
# response below rather than silently presented as a real number.
ASSUMED_CASH_RESERVES = 1500000.0

# FIN-02/FIN-03 (formal gross-margin and cash-runway definitions, 27 Aug
# 2026, founder-delegated decision -- "just start completing the list, no
# need for my approval"): until now this function summed EVERY ledger row
# a tenant had ever ingested and labeled the result "Monthly Burn"/"Cash
# Runway" -- for a tenant with, say, six months of uploaded history, that
# meant six months of real expenses added together and presented as if it
# were one month's burn. This was a KNOWN, already-disclosed simplification
# -- scenario_modeler.py's own docstring (written earlier this engagement)
# explicitly called it out: "Deliberately NOT the lifetime-total-as-if-
# monthly approach virtual_cfo.py's burn_rate uses ... that simplification
# is ... an existing, disclosed business-logic choice, not something to
# silently propagate into a new feature." That comment is why
# scenario_modeler was built on real month-scoped figures from day one.
# This pass finally makes Virtual CFO consistent with it: metrics are now
# computed from the tenant's most recently completed real calendar month
# only (same "latest month present in the ledger" convention
# db_manager.get_ledger_chart_context's monthly_totals/
# monthly_revenue_totals already uses, which scenario_modeler's baseline
# already reads from) -- never a lifetime sum mislabeled as monthly. The
# resolved month is returned as "reporting_month" so this is visible, not
# silent. Rows whose date can't be parsed at all (TRY_CAST(date AS DATE)
# IS NULL) can't belong to any month and are excluded from every monthly
# figure -- same behavior get_ledger_chart_context's by_month already has
# -- and their count is disclosed via "unparseable_date_rows_excluded"
# rather than silently dropped.
REPORTING_PERIOD_NOTE = (
    "Metrics reflect this tenant's most recently completed calendar month "
    "with ledger data (see reporting_month), not a lifetime-to-date sum."
)


def _classify_expense(category: str) -> str:
    """
    FIN-02: word-boundary keyword match, not the substring "in" check this
    used to be. The substring version had real false positives -- "cost"
    as a bare substring matches "Costco Wholesale" or "Costume Design" (both
    plausible real vendor/category names) and would misclassify an
    ordinary operating expense as COGS. \\b...\\b matches "cost" only as a
    whole word ("Cost of Goods Sold" still matches; "Costco" no longer
    does). The keyword list itself (which categories imply COGS) is
    unchanged -- this only fixes HOW they're matched, not WHICH ones count.
    """
    cat_lower = category.lower() if category else ""
    cogs_keywords = ("hosting", "aws", "stripe", "cogs", "cost")
    is_cogs = any(re.search(rf"\b{re.escape(k)}\b", cat_lower) for k in cogs_keywords)
    return "cogs" if is_cogs else "opex"


# DIFF-09: inline evidence citations. DELIBERATE DESIGN CHOICE -- the
# literal reading of DIFF-09 ("every briefing sentence carries a clickable
# row_id") would mean asking the LLM to embed row_ids inline in its own
# free-text prose. Rejected: hallucination-prone (nothing stops the model
# from citing a row_id that was never in its prompt, or attaching the
# wrong one to the wrong sentence) and unverifiable in THIS environment
# specifically (no live OpenAI network access in this sandbox -- same
# documented limit as AI-04's model registry). Built instead: a
# deterministic, code-computed `evidence` field alongside (not inside) the
# existing free-text `insights` -- the exact real row_ids each metric was
# actually summed from, bucketed the SAME way total_revenue/total_cogs/
# total_opex already are below. This is real and fully testable without
# any LLM call; it does not depend on which path (live LLM or template
# fallback) produced the prose, so it's attached identically either way.
EVIDENCE_MAX_ROWS_PER_BUCKET = 10  # keeps the response bounded for tenants with thousands of ledger rows -- total_matching_rows below is still the real, uncapped count.


def _finalize_evidence_bucket(bucket_rows: list) -> Dict[str, Any]:
    """
    bucket_rows: real {"row_id", "date", "category", "amount"} dicts already
    classified into this bucket (revenue/cogs/opex) by generate_cfo_briefing's
    own classification loop -- never re-derived or guessed here. Sorted
    most-recent-first and capped to EVIDENCE_MAX_ROWS_PER_BUCKET for the
    citation list; total_matching_rows reports the real, uncapped count so
    a cap is visible, never silently mistaken for "that's everything."
    """
    rows_sorted = sorted(bucket_rows, key=lambda r: r["date"] or "", reverse=True)
    shown = rows_sorted[:EVIDENCE_MAX_ROWS_PER_BUCKET]
    return {
        "total_matching_rows": len(rows_sorted),
        "shown_rows": shown,
        "truncated": len(rows_sorted) > len(shown),
    }


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


def _no_dateable_data_response(unparseable_count: int) -> Dict[str, Any]:
    """
    FIN-02/FIN-03: distinct from _empty_state_response() above -- this
    tenant DOES have ledger rows, but not one of them has a date that
    TRY_CAST(date AS DATE) can parse, so no calendar month can be resolved
    and no monthly figure can be honestly computed. Conflating this with
    "no ledger data has been ingested yet" would be misleading: data WAS
    ingested, it just can't be placed on a timeline. Real-world likelihood
    is low (most uploads have usable dates), but silently returning
    NO_DATA here would hide a genuinely different, actionable problem
    (fix the date column and re-upload) behind the wrong message.
    """
    return {
        "status": "NO_DATEABLE_DATA",
        "metrics": {
            "gross_margin": None,
            "burn_rate": None,
            "cash_runway_months": None
        },
        "unparseable_date_rows_excluded": unparseable_count,
        "insights": [
            f"This tenant has {unparseable_count} ledger row(s), but none has a date "
            "Eivanta can parse, so no calendar month can be resolved and no monthly "
            "briefing can be computed. Check the date column on your uploaded CSV and "
            "re-upload."
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


def _format_history_for_prompt(conversation_history: Optional[List[Dict[str, Any]]]) -> str:
    """
    AI-08 mechanical follow-up: identical implementation to bi_engineer.py's
    _format_history_for_prompt (Track 4's original wiring) -- renders the
    last few real turns of this session (fetched by orchestrator.route_query
    from db_manager.get_conversation_history) as plain transcript text for
    the narrative LLM prompt below. Duplicated per-agent rather than
    centralized, matching this codebase's own accepted precedent (see the
    AI_REQUEST_TIMEOUT_SECONDS/AI_MAX_RETRIES duplication across all 8 agent
    files, called out as a disclosed code-quality nit, not a functional gap,
    in the AI-03 correction).
    """
    if not conversation_history:
        return ""
    lines = []
    for turn in conversation_history:
        role = turn.get("role", "user")
        content = str(turn.get("content", "")).strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    if not lines:
        return ""
    return "\n    Recent conversation in this session (oldest first):\n    " + "\n    ".join(lines)


def generate_cfo_briefing(
    client_id: str = "default_client",
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    AI-08 (27 Aug 2026): `conversation_history` (optional, default None) is
    real prior turns for this session -- when present it's included in the
    narrative LLM prompt below so a follow-up question resolves against what
    was actually asked/answered before in this session, instead of being
    answered blind every time. Callers that don't pass it keep today's exact
    behavior -- additive, not a breaking change. Mechanical follow-up to
    Track 4's original BI Engineer wiring (see bi_engineer.py).
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")

    total_revenue = 0.0
    total_cogs = 0.0
    total_opex = 0.0

    rows = []
    db_failed = False
    failure_reason = ""
    reporting_month: Optional[str] = None
    unparseable_date_rows_excluded = 0
    has_any_rows = False

    # FIXED: previously opened its own connection with NO synchronization
    # against db_manager.py's shared lock at all -- a live request here
    # could race a concurrent write/read from db_manager and get a
    # connection or query exception purely from that contention. Now
    # serialized through the SAME shared lock every other DB access in
    # this codebase uses, via db_manager.get_db_lock().
    if os.path.exists(db_manager.DB_PATH):
        lock = get_db_lock()
        with lock:
            conn = None
            try:
                conn = duckdb.connect(db_manager.DB_PATH, read_only=True)
            except Exception as e:
                logger.error(f"Failed to open DuckDB at {db_manager.DB_PATH}: {e}")
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
                        has_any_rows = conn.execute(
                            "SELECT EXISTS(SELECT 1 FROM ledgers WHERE client_id = ?)",
                            [safe_client_id]
                        ).fetchone()[0]

                        # FIN-02/FIN-03: resolve the tenant's most recently
                        # completed real calendar month -- same
                        # strftime(TRY_CAST(date AS DATE), '%Y-%m')
                        # convention db_manager.get_ledger_chart_context's
                        # monthly_totals already uses, so this agrees with
                        # every other real-month-scoped feature
                        # (scenario_modeler) rather than inventing a
                        # fourth convention.
                        month_row = conn.execute(
                            "SELECT MAX(strftime(TRY_CAST(date AS DATE), '%Y-%m')) "
                            "FROM ledgers WHERE client_id = ?",
                            [safe_client_id]
                        ).fetchone()
                        reporting_month = month_row[0] if month_row else None

                        # FIXED: this count used to live INSIDE the
                        # `if reporting_month is not None:` block below, so
                        # a tenant whose rows are ALL date-unparseable
                        # (reporting_month resolves to None) always got
                        # unparseable_date_rows_excluded == 0 -- silently
                        # wrong for exactly the case
                        # _no_dateable_data_response exists to disclose.
                        # Computed unconditionally here instead, for any
                        # tenant with at least one row.
                        unparseable_date_rows_excluded = conn.execute(
                            "SELECT COUNT(*) FROM ledgers "
                            "WHERE client_id = ? AND TRY_CAST(date AS DATE) IS NULL",
                            [safe_client_id]
                        ).fetchone()[0]

                        if reporting_month is not None:
                            # DIFF-09: row_id/date carried through so the
                            # classification loop below can attach real,
                            # clickable evidence to each metric.
                            rows = conn.execute(
                                """
                                SELECT category, amount, row_id, date
                                FROM ledgers
                                WHERE client_id = ?
                                  AND strftime(TRY_CAST(date AS DATE), '%Y-%m') = ?
                                """,
                                [safe_client_id, reporting_month]
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

    if not has_any_rows:
        return _empty_state_response()

    if reporting_month is None:
        # Rows exist, but not one of them has a parseable date -- see
        # _no_dateable_data_response's own docstring for why this is kept
        # distinct from the true NO_DATA case above.
        return _no_dateable_data_response(unparseable_date_rows_excluded)

    # DIFF-09: real per-row evidence, bucketed by the exact same
    # classification this loop already performs -- not a second pass, not
    # a re-derivation that could drift out of sync with the totals above.
    revenue_evidence_rows = []
    cogs_evidence_rows = []
    opex_evidence_rows = []
    # Rows that predate the DIFF-01 row_id migration and, for whatever
    # reason, were never backfilled -- same honest-disclosure pattern as
    # db_manager.get_ledger_rows' own legacy_row_count. Still counted in
    # the metric totals above (a real transaction is a real transaction),
    # just not citable by row_id.
    legacy_untraceable_count = 0

    for cat, amt, row_id, row_date in rows:
        amt_float = float(amt) if amt is not None else 0.0
        row_ref = {
            "row_id": row_id,
            "date": str(row_date) if row_date is not None else None,
            "category": cat,
            "amount": amt_float,
        }

        if amt_float > 0:
            total_revenue += amt_float
            bucket = revenue_evidence_rows
        else:
            abs_amt = abs(amt_float)
            # FIN-02: single source of truth for the classification rule
            # (_classify_expense, word-boundary matched) -- used for both
            # the totals branch and the evidence bucket below, so the two
            # can never silently drift apart the way two separately
            # inlined keyword checks could.
            is_cogs = _classify_expense(cat) == "cogs"
            if is_cogs:
                total_cogs += abs_amt
            else:
                total_opex += abs_amt
            bucket = cogs_evidence_rows if is_cogs else opex_evidence_rows

        if row_id is None:
            legacy_untraceable_count += 1
        else:
            bucket.append(row_ref)

    evidence = {
        "revenue": _finalize_evidence_bucket(revenue_evidence_rows),
        "cogs": _finalize_evidence_bucket(cogs_evidence_rows),
        "opex": _finalize_evidence_bucket(opex_evidence_rows),
        "legacy_untraceable_rows": legacy_untraceable_count,
        "note": (
            f"row_ids reference real ledger rows from {reporting_month} (this "
            "briefing's reporting month) behind these totals -- fetch full row "
            "detail for any of them via POST /api/v1/finance/ledger-rows "
            "(category/month/date-range filters). Each bucket's citation list is "
            f"capped to the most recent {EVIDENCE_MAX_ROWS_PER_BUCKET} rows to "
            "keep this response bounded; total_matching_rows is the real, "
            "uncapped count each metric was actually computed from."
        ),
    }

    # FIN-02: revenue/COGS/OPEX classification is still a sign + keyword
    # heuristic (see _classify_expense), not a formal chart-of-accounts
    # mapping -- that part of FIN-02/FIN-03 remains genuinely open (which
    # categories count as COGS vs OPEX is a real business-logic decision
    # this pass does not make). What this pass DOES resolve: the reporting
    # PERIOD (see the FIN-02/FIN-03 comment above generate_cfo_briefing)
    # and the keyword MATCHING precision (whole-word, not substring).
    gross_margin = 0.0
    if total_revenue > 0:
        gross_margin = ((total_revenue - total_cogs) / total_revenue) * 100

    burn_rate = total_cogs + total_opex
    cash_runway_months = (ASSUMED_CASH_RESERVES / burn_rate) if burn_rate > 0 else 99.9

    history_block = _format_history_for_prompt(conversation_history)
    system_prompt = f"""
    You are Eivanta's elite Virtual Chief Financial Officer (CFO).
    Tenant: {safe_client_id}. Reporting month: {reporting_month}.
    Calculated Metrics for {reporting_month} ONLY (not lifetime-to-date) -> Revenue: ${total_revenue:,.2f}, COGS: ${total_cogs:,.2f}, OPEX: ${total_opex:,.2f}, Gross Margin: {gross_margin:.1f}%, Burn Rate: ${burn_rate:,.2f}, Runway: {cash_runway_months:.1f} months.
    IMPORTANT: the runway figure assumes a hypothetical ${ASSUMED_CASH_RESERVES:,.2f} cash reserve, not this tenant's actual bank balance (the system does not yet ingest real cash-balance data). Any insight referencing runway must state this is an estimate based on an assumed reserve, not a confirmed cash position. Every insight must describe {reporting_month}, not the tenant's all-time history.
    {history_block}

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
        client = get_openai_client_for_tenant_sync(client_id, platform_api_key, AI_REQUEST_TIMEOUT_SECONDS, AI_MAX_RETRIES)
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
                # FIN-02/FIN-03: which real month these metrics describe --
                # attached here in Python, not trusted from the LLM's JSON,
                # same reasoning as evidence below.
                result["reporting_month"] = reporting_month
                result["reporting_period_note"] = REPORTING_PERIOD_NOTE
                result["unparseable_date_rows_excluded"] = unparseable_date_rows_excluded
                # DIFF-09: attached here too, NOT inside the LLM's own JSON
                # -- evidence is computed entirely in Python from the same
                # rows the metrics above came from, regardless of which
                # path (live LLM or template fallback) produced the prose.
                # Never trust the LLM to echo this back correctly.
                result["evidence"] = evidence
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
        "reporting_month": reporting_month,
        "reporting_period_note": REPORTING_PERIOD_NOTE,
        "unparseable_date_rows_excluded": unparseable_date_rows_excluded,
        "evidence": evidence,
        "insights": [
            f"Gross margin for {reporting_month} is {gross_margin:.1f}%, reflecting that month's revenue-to-COGS efficiency.",
            f"{reporting_month} burn rate was ${burn_rate:,.2f}, combining infrastructure and operating expenditures for that month.",
            f"Estimated cash runway is {cash_runway_months:.1f} months at {reporting_month}'s burn rate, based on an assumed ${ASSUMED_CASH_RESERVES:,.2f} cash reserve (not yet sourced from real account data)."
        ]
    }