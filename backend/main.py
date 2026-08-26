import os
import logging
import asyncio
import glob
import statistics
from pathlib import Path
from typing import Optional, Union
from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)
from backend.db_manager import ingest_csv_to_db
from backend.auth import verify_jwt_and_get_client_id, require_role, AuthenticatedUser
def get_active_agent_count() -> int:
    try:
        agents_dir = os.path.join(os.path.dirname(__file__), 'agents')
        agent_files = glob.glob(os.path.join(agents_dir, '*.py'))
        return len([f for f in agent_files if not f.endswith('__init__.py')])
    except Exception:
        return 0
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("eivanta.supervisor")
app = FastAPI(title="Eivanta Backend - Hardened Enterprise Edition")
try:
    from backend import accounts
    app.include_router(accounts.router)
except ImportError as e:
    logger.error(f"Failed to load accounts router: {e}")
try:
    from backend.routers import swarm
    app.include_router(swarm.router)
except ImportError as e:
    logger.error(f"Failed to load swarm router: {e}")
try:
    from backend import metrics
    app.include_router(metrics.router)
except ImportError as e:
    logger.error(f"Failed to load metrics router: {e}")
try:
    from backend import assumptions
    app.include_router(assumptions.router)
except ImportError as e:
    logger.error(f"Failed to load assumptions router: {e}")
try:
    from backend import gaps
    app.include_router(gaps.router)
except ImportError as e:
    logger.error(f"Failed to load gaps router: {e}")
try:
    from backend import evidence
    app.include_router(evidence.router)
except ImportError as e:
    logger.error(f"Failed to load evidence router: {e}")
try:
    from backend import categorization
    app.include_router(categorization.router)
except ImportError as e:
    logger.error(f"Failed to load categorization router: {e}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8001", "http://127.0.0.1:8001"],
    allow_credentials=True,
    # DELETE added alongside the new DATA-09 explicit ledger-deletion
    # endpoint below -- without it, a browser's CORS preflight would block
    # that request before it ever reached the server.
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';"
    return response
class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None
    sample_payload: Optional[Union[str, dict, list]] = None

class BISummaryRequest(BaseModel):
    # Optional ad hoc question for BI Engineer's NL-to-SQL capability
    # (SQL-01/SQL-03). Defaults to empty string, matching
    # generate_bi_summary's own default -- an empty query short-circuits
    # to NO_QUESTION_ASKED in bi_engineer.py's _answer_data_question
    # before any second LLM call happens, so callers who don't send a
    # body (or send an empty query) see no behavior change and no added
    # cost versus before this field existed.
    query: str = Field("", max_length=2000)
MAX_UPLOAD_BYTES = int(os.environ.get("EIVANTA_MAX_UPLOAD_BYTES", 25 * 1024 * 1024))
@app.get("/api/v1/health")
async def get_health():
    active_agents = get_active_agent_count()
    return {
        "status": "ONLINE",
        "docker_detected": os.path.exists("/.dockerenv"),
        "active_agent_modules": active_agents,
        "version": "2.2.1 (Hardened Production Architecture)"
    }
# RBAC-01: /api/v1/auth/dev-login is retired, not just deprecated -- its
# own comment said it "must be replaced, not just left in place" during
# the auth-hardening pass, and this is that pass. Real signup/login/team
# management now live in backend/accounts.py (registered in the router
# block above main.py's other routers). Anything still calling
# dev-login (a stale frontend build, an old test fixture) gets a real
# 404, not a silent security hole.
@app.post("/api/finance/upload-ledger")
async def upload_ledger(
    file: UploadFile = File(...),
    # RBAC-01: mutates real tenant data (ingests rows) -- viewer excluded.
    user: AuthenticatedUser = Depends(require_role("owner", "admin", "member")),
):
    client_id = user.client_id
    safe_filename = Path(file.filename or "upload.csv").name
    temp_dir = Path("/tmp/eivanta_ingest")
    temp_dir.mkdir(parents=True, exist_ok=True)
    file_path = temp_dir / f"{client_id}_{safe_filename}"
    bytes_written = 0
    try:
        with open(file_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds maximum allowed size.")
                buffer.write(chunk)
        result_msg = await ingest_csv_to_db(str(file_path), client_id, original_filename=safe_filename)
        return {"status": "SUCCESS", "message": result_msg}
    except HTTPException:
        raise
    except ValueError as e:
        # DATA-03: a structural problem with the file itself (ragged rows,
        # empty file, duplicate columns, unrecognized amount column, every
        # row unparseable, over the row/column caps) -- this is the
        # uploader's file, not a server fault, so it's a 400 with the
        # actual specific reason, not a generic 500.
        logger.warning(f"Ledger upload rejected for tenant '{client_id}': {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Ledger upload error: {e}")
        raise HTTPException(status_code=500, detail="Ledger ingestion failed. Check server logs for details.")
    finally:
        if file_path.exists():
            file_path.unlink()


@app.get("/api/v1/data/ingestion-history")
async def get_ingestion_history_endpoint(
    limit: int = 20,
    client_id: str = Depends(verify_jwt_and_get_client_id),
):
    # DATA-08: tenant-scoped ingestion history -- status/errors per past
    # upload attempt, not just the current state of the ledgers table.
    try:
        from backend.db_manager import get_ingestion_history
        history = await get_ingestion_history(client_id, limit=limit)
        return {"client_id": client_id, "history": history}
    except Exception as e:
        logger.error(f"Ingestion history fetch error: {e}")
        raise HTTPException(status_code=502, detail="Could not fetch ingestion history. Please try again.")


@app.delete("/api/v1/finance/ledger")
async def delete_ledger_endpoint(
    # RBAC-01: destructive, irreversible, wipes ALL of this tenant's
    # ledger data at once -- restricted to owner/admin, not member/viewer.
    user: AuthenticatedUser = Depends(require_role("owner", "admin")),
):
    # DATA-09: explicit deletion API for a tenant's own ledger data.
    # client_id comes ONLY from the verified JWT dependency above -- never
    # accepted as a request parameter -- so this can only ever delete the
    # caller's own tenant's data, never another tenant's.
    client_id = user.client_id
    try:
        from backend.db_manager import delete_tenant_ledger
        deleted_count = await delete_tenant_ledger(client_id)
        return {
            "status": "SUCCESS",
            "client_id": client_id,
            "rows_deleted": deleted_count,
            "message": f"Deleted {deleted_count} ledger row(s) for this tenant.",
        }
    except Exception as e:
        logger.error(f"Ledger deletion error: {e}")
        raise HTTPException(status_code=502, detail="Ledger deletion failed. Please try again.")
@app.post("/api/search")
async def secure_cognitive_search(
    req: SearchRequest,
    client_id: str = Depends(verify_jwt_and_get_client_id),
):
    try:
        from backend.agents.ops_shield import analyze_threat
        threat_result = await asyncio.to_thread(analyze_threat, client_id, req.query)
    except Exception as e:
        logger.error(f"Ops Shield invocation error: {e}")
        raise HTTPException(status_code=503, detail="Security firewall unavailable. Please try again.")
    if threat_result.get("status") != "SECURE":
        logger.warning(f"Ops Shield blocked a request for tenant '{client_id}': {threat_result.get('reason')}")
        raise HTTPException(status_code=403, detail="Request blocked by security policy.")
    try:
        from backend.agents.orchestrator import route_query
        result = await asyncio.to_thread(route_query, req.query, client_id, req.session_id, req.sample_payload)
        return result
    except Exception as e:
        logger.error(f"Cognitive search routing error: {e}")
        raise HTTPException(status_code=502, detail="Search routing failed. Please try again.")
@app.post("/api/v1/finance/cfo-briefing")
async def get_cfo_briefing(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        from backend.agents.virtual_cfo import generate_cfo_briefing
        result = await asyncio.to_thread(generate_cfo_briefing, client_id)
        return result
    except Exception as e:
        logger.error(f"CFO Briefing Error: {e}")
        raise HTTPException(status_code=502, detail="CFO briefing generation failed. Please try again.")
@app.post("/api/v1/finance/kpi-summary")
async def get_kpi_summary(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        from backend.db_manager import get_ledger_chart_context, get_mrr_summary
        from datetime import date
        context = await get_ledger_chart_context(client_id)
        mrr_summary = await get_mrr_summary(client_id)
        ledger_total_amount = round(
            sum(c["total_amount"] for c in context.get("category_breakdown", [])), 2
        )
        current_month_key = date.today().strftime("%Y-%m")
        monthly_revenue = next(
            (m["total_amount"] for m in context.get("monthly_totals", []) if m["month"] == current_month_key),
            0.0,
        )
        return {
            "ledger_total_amount": ledger_total_amount,
            "ledger_row_count": context.get("row_count", 0),
            # Labeled honestly as "Monthly Revenue", not "MRR" -- this is
            # simply ALL transactions (recurring or not) for the current
            # month, net of nothing. Kept as-is for anyone already reading
            # it; the real MRR fields below are the FIN-01 addition.
            "monthly_revenue": monthly_revenue,
            "monthly_revenue_label": "Monthly Revenue",
            "revenue_month": current_month_key,
            # FIN-01: real Monthly Recurring Revenue -- computed ONLY from
            # transactions this tenant explicitly flagged recurring on
            # upload (a 'recurring'/'is_recurring' CSV column; see
            # db_manager.get_mrr_summary). mrr is None and mrr_available is
            # False for a tenant that has never provided the flag on any
            # upload -- never silently backfilled from monthly_revenue
            # above, and never guessed from category names.
            "mrr": mrr_summary["mrr"],
            "mrr_available": mrr_summary["mrr_available"],
            "mrr_note": mrr_summary["note"],
        }
    except Exception as e:
        logger.error(f"KPI Summary Error: {e}")
        raise HTTPException(status_code=502, detail="KPI summary generation failed. Please try again.")
@app.post("/api/v1/finance/comptroller-audit")
async def run_comptroller_audit(client_id: str = Depends(verify_jwt_and_get_client_id)):
    """
    Track 5 (Interactive audit trigger): real expense audit over this
    tenant's own ledger -- category totals plus a genuine statistical
    spike-anomaly check (z-score on transaction amount within each
    category), not a canned/mocked response. Any category with fewer than
    3 transactions is skipped for anomaly scoring (stdev is meaningless
    below that), but its transactions still count toward the totals and
    the audited count.
    """
    try:
        from backend.db_manager import get_ledger_rows
        ledger = await get_ledger_rows(client_id, limit=1000)
        rows = ledger.get("rows", [])

        by_category: dict[str, list[dict]] = {}
        for row in rows:
            cat = row.get("category") or "Uncategorized"
            by_category.setdefault(cat, []).append(row)

        expense_breakdown_by_category = {
            cat: round(sum(r["amount"] for r in cat_rows), 2)
            for cat, cat_rows in by_category.items()
        }

        ANOMALY_ZSCORE_THRESHOLD = 2.5
        flagged_items = []
        for cat, cat_rows in by_category.items():
            if len(cat_rows) < 3:
                continue
            amounts = [r["amount"] for r in cat_rows]
            mean = statistics.mean(amounts)
            stdev = statistics.stdev(amounts)
            if stdev == 0:
                continue
            for r in cat_rows:
                z = (r["amount"] - mean) / stdev
                if abs(z) >= ANOMALY_ZSCORE_THRESHOLD:
                    flagged_items.append({
                        "tx_id": str(r.get("row_id")) if r.get("row_id") is not None else f"{cat}:{r.get('date')}",
                        "amount": r["amount"],
                        "category": cat,
                        "reason": f"{abs(z):.1f} std devs {'above' if z > 0 else 'below'} this category's average ({mean:,.2f}).",
                    })

        return {
            "total_transactions_audited": len(rows),
            "flagged_count": len(flagged_items),
            "expense_breakdown_by_category": expense_breakdown_by_category,
            "flagged_items": flagged_items,
            "audit_status": "COMPLETE" if rows else "NO_DATA",
        }
    except Exception as e:
        logger.error(f"Comptroller Audit Error: {e}")
        raise HTTPException(status_code=502, detail="Ledger audit failed. Please try again.")
class BYOKKeyRequest(BaseModel):
    openai_api_key: str = Field(..., min_length=1)


@app.get("/api/v1/settings/byok")
async def get_byok_status(client_id: str = Depends(verify_jwt_and_get_client_id)):
    """
    Never returns the key itself, encrypted or otherwise -- only whether
    one is configured. The key round-trips through backend/byok.py's
    encrypt/decrypt exactly once: on save, and whenever an agent actually
    needs it to call OpenAI.
    """
    try:
        from backend.db_manager import get_tenant_byok_key_encrypted
        encrypted = await get_tenant_byok_key_encrypted(client_id)
        return {"byok_configured": bool(encrypted)}
    except Exception as e:
        logger.error(f"BYOK status check error: {e}")
        raise HTTPException(status_code=502, detail="Could not check BYOK status.")


@app.post("/api/v1/settings/byok")
async def set_byok_key(req: BYOKKeyRequest, user: AuthenticatedUser = Depends(require_role("owner", "admin"))):
    try:
        from backend.byok import encrypt_secret
        from backend.db_manager import set_tenant_byok_key
        encrypted = encrypt_secret(req.openai_api_key)
        await set_tenant_byok_key(user.client_id, encrypted)
        return {"byok_configured": True}
    except RuntimeError as e:
        # BYOK_ENCRYPTION_KEY missing/invalid, or `cryptography` not
        # installed -- an operator/config problem, not a bad request from
        # the tenant, so this is a 503 rather than a 400/422.
        logger.error(f"BYOK save blocked by server configuration: {e}")
        raise HTTPException(status_code=503, detail="BYOK is not configured on this server yet. Contact your administrator.")
    except Exception as e:
        logger.error(f"BYOK save error: {e}")
        raise HTTPException(status_code=502, detail="Could not save your API key. Please try again.")


@app.delete("/api/v1/settings/byok")
async def delete_byok_key(user: AuthenticatedUser = Depends(require_role("owner", "admin"))):
    try:
        from backend.db_manager import set_tenant_byok_key
        await set_tenant_byok_key(user.client_id, None)
        return {"byok_configured": False}
    except Exception as e:
        logger.error(f"BYOK delete error: {e}")
        raise HTTPException(status_code=502, detail="Could not remove your API key. Please try again.")
@app.post("/api/v1/data/schema-audit")
async def run_schema_audit(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        from backend.agents.data_engineer import analyze_schema_quality
        result = await asyncio.to_thread(analyze_schema_quality, client_id)
        return result
    except Exception as e:
        logger.error(f"Data Engineer Audit Error: {e}")
        raise HTTPException(status_code=502, detail="Schema audit failed. Please try again.")
@app.post("/api/v1/bi/summary")
async def get_bi_summary(
    req: BISummaryRequest = BISummaryRequest(),
    client_id: str = Depends(verify_jwt_and_get_client_id),
):
    try:
        from backend.agents.bi_engineer import generate_bi_summary
        result = await asyncio.to_thread(generate_bi_summary, client_id, req.query)
        return result
    except Exception as e:
        logger.error(f"BI Summary Error: {e}")
        raise HTTPException(status_code=502, detail="BI summary generation failed. Please try again.")
@app.post("/api/v1/predictive/forecast")
async def get_forecast(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        from backend.agents.predictive_forecaster import generate_forecast
        result = await asyncio.to_thread(generate_forecast, client_id)
        return result
    except Exception as e:
        logger.error(f"Forecaster Error: {e}")
        raise HTTPException(status_code=502, detail="Forecast generation failed. Please try again.")
@app.get("/api/v1/finance/forecast-accuracy")
async def get_forecast_accuracy_endpoint(client_id: str = Depends(verify_jwt_and_get_client_id)):
    # FIN-04: backtesting -- compares every forecast this tenant has ever
    # generated (predictive_forecaster.generate_forecast now snapshots each
    # run via log_forecast_snapshot_sync) against real ledger revenue for
    # any month that has since occurred. Tenant-scoped like every other
    # finance endpoint; not a cross-tenant view.
    try:
        from backend.db_manager import get_forecast_accuracy
        result = await get_forecast_accuracy(client_id)
        return result
    except Exception as e:
        logger.error(f"Forecast Accuracy Error: {e}")
        raise HTTPException(status_code=502, detail="Forecast accuracy lookup failed. Please try again.")
@app.post("/api/v1/saas/strategy")
async def get_saas_strategy(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        from backend.agents.saas_strategist import generate_strategy
        result = await asyncio.to_thread(generate_strategy, client_id)
        return result
    except Exception as e:
        logger.error(f"SaaS Strategist Error: {e}")
        raise HTTPException(status_code=502, detail="Strategy generation failed. Please try again.")
@app.post("/api/v1/bi/chart-suite")
async def get_chart_suite(client_id: str = Depends(verify_jwt_and_get_client_id)):
    # generate_chart_suite is `async` and MUST be awaited directly here, on
    # this same running event loop -- NOT wrapped in asyncio.to_thread(...).
    # An earlier version did wrap it that way (matching
    # bi_visualization_architect.execute_task's existing pattern), and that
    # wrapper's internal asyncio.run() call bound db_manager's shared
    # asyncio.Lock singleton to a throwaway loop that no longer existed the
    # moment the call returned -- which then broke every OTHER endpoint
    # that touches that same lock (KPI Summary, Analytics Summary) with
    # "Lock object ... is bound to a different event loop", confirmed live.
    # See the long comment on generate_chart_suite itself for the fuller
    # explanation and the still-open architectural question this exposed.
    try:
        from backend.agents.bi_visualization_architect import generate_chart_suite
        result = await generate_chart_suite(client_id)
        return result
    except Exception as e:
        logger.error(f"Chart Suite Error: {e}")
        raise HTTPException(status_code=502, detail="Chart suite generation failed. Please try again.")
@app.post("/api/v1/finance/analytics-summary")
async def get_analytics_summary(client_id: str = Depends(verify_jwt_and_get_client_id)):
    # Real, pure-arithmetic replacement for the numbers
    # AdvancedAnalyticsDashboard.tsx used to hardcode client-side
    # ($124,500 / $45,070 / $79,430) whenever its old fetch failed (which
    # was always -- it never sent an Authorization header, and its
    # expected response shape didn't exist on any real endpoint). No LLM
    # involved here, same style as /api/v1/finance/kpi-summary.
    try:
        from backend.db_manager import get_ledger_chart_context
        context = await get_ledger_chart_context(client_id)
        category_breakdown = context.get("category_breakdown", [])
        if not category_breakdown:
            return {
                "status": "NO_DATA",
                "total_revenue": 0.0,
                "total_expense": 0.0,
                "net_profit": 0.0,
                "trend_note": "No ledger data has been ingested yet for this tenant.",
            }

        total_revenue = round(sum(c["total_amount"] for c in category_breakdown if c["total_amount"] > 0), 2)
        total_expense = round(sum(abs(c["total_amount"]) for c in category_breakdown if c["total_amount"] < 0), 2)
        net_profit = round(total_revenue - total_expense, 2)

        monthly_totals = context.get("monthly_totals", [])
        if len(monthly_totals) >= 2:
            prev_rev = monthly_totals[-2]["total_amount"]
            last_rev = monthly_totals[-1]["total_amount"]
            if prev_rev:
                mom_pct = round((last_rev - prev_rev) / prev_rev * 100, 1)
                trend_note = f"{mom_pct:+.1f}% vs. the previous recorded month (real month-over-month change)."
            else:
                trend_note = "Previous recorded month had no revenue; a percent change isn't meaningful here."
        else:
            trend_note = "Fewer than two distinct months on file -- no month-over-month trend yet."

        return {
            "status": "OK",
            "total_revenue": total_revenue,
            "total_expense": total_expense,
            "net_profit": net_profit,
            "trend_note": trend_note,
        }
    except Exception as e:
        logger.error(f"Analytics Summary Error: {e}")
        raise HTTPException(status_code=502, detail="Analytics summary generation failed. Please try again.")
@app.post("/api/v1/reports/stakeholder")
async def get_stakeholder_report(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        from backend.agents.report_generator import generate_stakeholder_report
        result = await asyncio.to_thread(generate_stakeholder_report, client_id)
        return result
    except Exception as e:
        logger.error(f"Report Generator Error: {e}")
        raise HTTPException(status_code=502, detail="Stakeholder report generation failed. Please try again.")
