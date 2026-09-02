import os
import logging
import asyncio
import contextlib
import glob
import statistics
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Union
from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)
from backend.db_manager import ingest_csv_to_db, init_telemetry_schema
from backend.auth import verify_jwt_and_get_client_id, verify_jwt_and_get_user, require_role, AuthenticatedUser
from backend.rate_limit import check_ingestion_rate_limit
def get_active_agent_count() -> int:
    try:
        agents_dir = os.path.join(os.path.dirname(__file__), 'agents')
        agent_files = glob.glob(os.path.join(agents_dir, '*.py'))
        return len([f for f in agent_files if not f.endswith('__init__.py')])
    except Exception:
        return 0
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("eivanta.supervisor")

# INT-01: the MCP read-only tool server's Streamable HTTP transport runs
# its own internal task group (see backend/mcp_server.py's mcp_lifespan
# docstring) that must be started via a real ASGI lifespan -- mounting the
# sub-app with app.mount() alone does NOT do this. Resolved BEFORE the
# FastAPI() call below so it can be passed as this app's own lifespan.
# Same fail-closed-and-loud posture as every router import below: a
# missing 'mcp' package (see requirements.txt) disables the /mcp mount
# entirely, logged once here, rather than crashing the whole backend.
_mcp_asgi_app = None
_mcp_lifespan = None
try:
    from backend import mcp_server as _mcp_server_module
    # A fresh FastMCP instance (and its matched asgi app + lifespan) is
    # built HERE, once per import of this module -- not once per process
    # -- so re-importing/reloading backend.main (as the real test suite's
    # `app` fixture does per test) always gets its own never-yet-started
    # session manager. See mcp_server.create_mcp_asgi_app_and_lifespan's
    # own docstring for why a shared module-level singleton breaks this.
    _mcp_asgi_app, _mcp_lifespan = _mcp_server_module.create_mcp_asgi_app_and_lifespan()
except ImportError as e:
    logger.error(f"MCP tool server unavailable (INT-01) -- is 'mcp' installed? {e}")


# OPS-09 (27 Aug 2026): metrics.py used to register its own telemetry-schema
# init via the deprecated `@router.on_event("startup")` FastAPI hook -- that
# decorator is deprecated (still functional as of fastapi 0.141.1, but on a
# removal path) in favor of the app-level `lifespan` context manager below,
# which this app already had for INT-01's MCP session-manager startup/
# shutdown. Tracked here (not inside metrics.py) because only main.py knows
# whether the metrics router actually loaded -- see _metrics_router_loaded
# just below, set once the import a few lines down either succeeds or fails.
_metrics_router_loaded = False


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI):
    if _metrics_router_loaded:
        # Same "must run after the real event loop exists" requirement the
        # old on_event handler had -- this lifespan only starts running once
        # uvicorn's loop is live, same as on_event startup did. Gated on
        # _metrics_router_loaded so behavior matches the old on_event
        # handler exactly: a handler registered on a router that never got
        # included would never have fired either.
        await init_telemetry_schema()
    if _mcp_lifespan is not None:
        async with _mcp_lifespan():
            yield
    else:
        yield


app = FastAPI(title="Eivanta Backend - Hardened Enterprise Edition", lifespan=_lifespan)
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
    _metrics_router_loaded = True
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
try:
    from backend import api_keys
    app.include_router(api_keys.router)
except ImportError as e:
    logger.error(f"Failed to load api_keys router: {e}")
# INT-01: the actual MCP tool server mount -- a plain ASGI sub-app, not a
# FastAPI router, so it's app.mount()-ed rather than include_router()-ed.
# _mcp_asgi_app is None (with the reason already logged above) if the
# 'mcp' package isn't installed; guarded the same fail-closed way as every
# router include above rather than letting a missing optional dependency
# crash startup.
if _mcp_asgi_app is not None:
    try:
        app.mount("/mcp", _mcp_asgi_app)
    except Exception as e:
        logger.error(f"Failed to mount MCP tool server at /mcp: {e}")
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
@app.get("/api/v1/health", tags=["Health"])
async def get_health():
    active_agents = get_active_agent_count()
    return {
        "status": "ONLINE",
        "docker_detected": os.path.exists("/.dockerenv"),
        "active_agent_modules": active_agents,
        "version": "2.2.1 (Hardened Production Architecture)"
    }
# FINOPS-01: real billing-overrun protection, not just monitoring. Composes
# on top of the same real JWT auth every other endpoint already requires,
# then checks this tenant's real ai_usage-derived monthly spend against
# their optional cap (db_manager.check_budget_gate) before the request is
# allowed to trigger another billable LLM call. No cap set (every tenant's
# default) -> always allowed, identical to today's behavior. Applied so far
# to the AI-calling endpoints below that take a plain client_id dependency
# (search, CFO briefing, schema audit, BI summary, forecast, SaaS strategy,
# chart suite, stakeholder report) -- the knowledge-base endpoints
# (embeddings, a materially cheaper call) use a role-gated AuthenticatedUser
# dependency instead and aren't wired to this gate yet; extending it there
# is the same one-line composition, not done in this pass.
async def enforce_budget_gate(client_id: str = Depends(verify_jwt_and_get_client_id)) -> str:
    try:
        from backend.db_manager import check_budget_gate
        gate = await check_budget_gate(client_id)
    except Exception as e:
        # A failure to CHECK the budget must never itself block a tenant
        # who may well be well under any cap -- same fail-open-on-telemetry-
        # failure discipline as every audit/usage logger in db_manager.py.
        # (Deliberately the opposite posture from Ops Shield, which
        # fails CLOSED -- that is a security control; this is a billing
        # control, and a billing-check outage should never look like a
        # security block to the tenant.)
        logger.error(f"Budget gate check failed for tenant '{client_id}', allowing request: {e}")
        return client_id
    if not gate.get("allowed", True):
        raise HTTPException(
            status_code=402,
            detail=(
                f"Monthly AI usage cap reached (${gate['usage_usd']:.2f} of ${gate['cap_usd']:.2f}). "
                "Raise or remove your cap in Settings to continue."
            ),
        )
    return client_id


# SQL-03 (27 Aug 2026): identical budget-gate check as enforce_budget_gate
# above, but returns the full AuthenticatedUser instead of a bare client_id
# string, so callers that need user-level attribution (currently: the two
# endpoints that ultimately write a query_audit row) can get it without
# changing enforce_budget_gate's existing plain-string contract, which
# 7+ other endpoints already depend on unchanged.
async def enforce_budget_gate_for_user(user: AuthenticatedUser = Depends(verify_jwt_and_get_user)) -> AuthenticatedUser:
    try:
        from backend.db_manager import check_budget_gate
        gate = await check_budget_gate(user.client_id)
    except Exception as e:
        logger.error(f"Budget gate check failed for tenant '{user.client_id}', allowing request: {e}")
        return user
    if not gate.get("allowed", True):
        raise HTTPException(
            status_code=402,
            detail=(
                f"Monthly AI usage cap reached (${gate['usage_usd']:.2f} of ${gate['cap_usd']:.2f}). "
                "Raise or remove your cap in Settings to continue."
            ),
        )
    return user
# RBAC-01: /api/v1/auth/dev-login is retired, not just deprecated -- its
# own comment said it "must be replaced, not just left in place" during
# the auth-hardening pass, and this is that pass. Real signup/login/team
# management now live in backend/accounts.py (registered in the router
# block above main.py's other routers). Anything still calling
# dev-login (a stale frontend build, an old test fixture) gets a real
# 404, not a silent security hole.
@app.post("/api/finance/upload-ledger", tags=["Ledger & Ingestion"])
async def upload_ledger(
    file: UploadFile = File(...),
    # RBAC-01: mutates real tenant data (ingests rows) -- viewer excluded.
    user: AuthenticatedUser = Depends(require_role("owner", "admin", "member")),
):
    client_id = user.client_id
    # DATA-06: enforced BEFORE any file I/O or DB work -- a tenant already
    # over the limit shouldn't cost this server the price of a real
    # ingestion attempt just to find that out. See rate_limit.py's own
    # module docstring for why this is in-memory/per-process rather than
    # DB-backed, and what upgrading it would take.
    check_ingestion_rate_limit(client_id)
    safe_filename = Path(file.filename or "upload.csv").name
    # SEC-03 SAST (28 Aug 2026, bandit B108): a predictable, shared /tmp
    # path with default (umask-derived, typically world-readable) directory
    # permissions is a real hardening gap, even though this single-process
    # container has no other untrusted local process to exploit it today --
    # explicitly locking the directory to owner-only closes it regardless of
    # deployment topology. os.chmod is called unconditionally (not just
    # on first creation) because mkdir(mode=...) only applies its mode when
    # it actually creates the directory -- exist_ok=True silently skips it
    # on every later call, which would leave a looser-permissioned directory
    # from an old process/deploy unfixed. A uuid component was also added
    # to the filename (matching the knowledge-upload endpoint below, which
    # already had one) -- without it, two concurrent uploads of the same
    # filename from the same tenant collide on this exact path.
    temp_dir = Path("/tmp/eivanta_ingest")  # nosec B108 -- locked to 0700 immediately below, unconditionally, every request
    temp_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(temp_dir, 0o700)
    file_path = temp_dir / f"{client_id}_{uuid.uuid4().hex}_{safe_filename}"
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


@app.get("/api/v1/data/ingestion-history", tags=["Ledger & Ingestion"])
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


@app.delete("/api/v1/finance/ledger", tags=["Ledger & Ingestion"])
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
@app.post("/api/search", tags=["Search"])
async def secure_cognitive_search(
    req: SearchRequest,
    user: AuthenticatedUser = Depends(enforce_budget_gate_for_user),
):
    client_id = user.client_id
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
        result = await asyncio.to_thread(
            route_query, req.query, client_id, req.session_id, req.sample_payload, user.user_id
        )
        return result
    except Exception as e:
        logger.error(f"Cognitive search routing error: {e}")
        raise HTTPException(status_code=502, detail="Search routing failed. Please try again.")
@app.post("/api/v1/finance/cfo-briefing", tags=["BI & Analytics"])
async def get_cfo_briefing(client_id: str = Depends(enforce_budget_gate)):
    try:
        from backend.agents.virtual_cfo import generate_cfo_briefing
        result = await asyncio.to_thread(generate_cfo_briefing, client_id)
        return result
    except Exception as e:
        logger.error(f"CFO Briefing Error: {e}")
        raise HTTPException(status_code=502, detail="CFO briefing generation failed. Please try again.")
@app.post("/api/v1/finance/kpi-summary", tags=["BI & Analytics"])
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
        # BUG FIX (confirmed live 26 Aug 2026, founder-requested): this field used to
        # read straight from context["monthly_totals"], which nets revenue and
        # expense together for the month -- despite being labeled "Monthly Revenue"
        # and captioned on the frontend as "total revenue this month". On this
        # tenant's real test ledger that showed a NEGATIVE number for August
        # ($-33,822.95) as "revenue", when actual August revenue was a positive
        # $14,700. Now reads context["monthly_revenue_totals"] (amount > 0 only,
        # same field added for the analytics-summary/chart fixes above), so this is
        # real revenue math, not a net position mislabeled as revenue.
        monthly_revenue = next(
            (m["total_amount"] for m in context.get("monthly_revenue_totals", []) if m["month"] == current_month_key),
            0.0,
        )
        # Real math, not a guess: net position for the month (from monthly_totals,
        # which IS revenue+expense combined -- that's what "net" means) minus real
        # revenue gives real expense for the same month. All three numbers are
        # derived directly from this tenant's own ledger rows, nothing assumed.
        monthly_net = next(
            (m["total_amount"] for m in context.get("monthly_totals", []) if m["month"] == current_month_key),
            0.0,
        )
        monthly_expense = round(monthly_revenue - monthly_net, 2)
        return {
            "ledger_total_amount": ledger_total_amount,
            "ledger_row_count": context.get("row_count", 0),
            # Labeled "Monthly Revenue" and now IS real revenue -- current month's
            # rows with amount > 0 only, no expenses netted in. monthly_expense and
            # monthly_net_profit below are the same-month breakdown so the frontend
            # can show real revenue/expense/net together instead of one ambiguous
            # number; the real MRR fields further below are the separate FIN-01
            # addition (recurring-flagged rows only, not the same thing as this).
            "monthly_revenue": monthly_revenue,
            "monthly_revenue_label": "Monthly Revenue",
            "monthly_expense": monthly_expense,
            "monthly_net_profit": round(monthly_net, 2),
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
@app.post("/api/v1/finance/comptroller-audit", tags=["BI & Analytics"])
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


@app.get("/api/v1/settings/byok", tags=["Settings"])
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


@app.post("/api/v1/settings/byok", tags=["Settings"])
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


@app.delete("/api/v1/settings/byok", tags=["Settings"])
async def delete_byok_key(user: AuthenticatedUser = Depends(require_role("owner", "admin"))):
    try:
        from backend.db_manager import set_tenant_byok_key
        await set_tenant_byok_key(user.client_id, None)
        return {"byok_configured": False}
    except Exception as e:
        logger.error(f"BYOK delete error: {e}")
        raise HTTPException(status_code=502, detail="Could not remove your API key. Please try again.")


# ---------------------------------------------------------------------------
# FINOPS-01: per-tenant monthly AI spend cap -- settings + real gate check
# (enforce_budget_gate above). Same shape as the BYOK settings endpoints
# just above: GET is readable by any authenticated role on this tenant,
# mutation is owner/admin only.
# ---------------------------------------------------------------------------

class BudgetCapRequest(BaseModel):
    monthly_cap_usd: float = Field(..., gt=0)


@app.get("/api/v1/settings/budget", tags=["Settings"])
async def get_budget_status(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        from backend.db_manager import check_budget_gate
        return await check_budget_gate(client_id)
    except Exception as e:
        logger.error(f"Budget status check error: {e}")
        raise HTTPException(status_code=502, detail="Could not check budget status.")


@app.post("/api/v1/settings/budget", tags=["Settings"])
async def set_budget_cap(req: BudgetCapRequest, user: AuthenticatedUser = Depends(require_role("owner", "admin"))):
    try:
        from backend.db_manager import set_tenant_budget_cap, check_budget_gate
        await set_tenant_budget_cap(user.client_id, req.monthly_cap_usd)
        return await check_budget_gate(user.client_id)
    except Exception as e:
        logger.error(f"Budget cap save error: {e}")
        raise HTTPException(status_code=502, detail="Could not save your budget cap. Please try again.")


@app.delete("/api/v1/settings/budget", tags=["Settings"])
async def delete_budget_cap(user: AuthenticatedUser = Depends(require_role("owner", "admin"))):
    try:
        from backend.db_manager import set_tenant_budget_cap, check_budget_gate
        await set_tenant_budget_cap(user.client_id, None)
        return await check_budget_gate(user.client_id)
    except Exception as e:
        logger.error(f"Budget cap delete error: {e}")
        raise HTTPException(status_code=502, detail="Could not remove your budget cap. Please try again.")


# ---------------------------------------------------------------------------
# ENT-03: explainable-AI audit/lineage log -- read-only endpoints over
# db_manager's hash-chained ai_lineage_log. Any authenticated tenant role
# can view their own lineage (it's a transparency feature, not a mutation),
# same access level as the ingestion-history endpoint above.
# ---------------------------------------------------------------------------

@app.get("/api/v1/audit/lineage", tags=["Audit & Compliance"])
async def get_audit_lineage(limit: int = 100, client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        from backend.db_manager import get_lineage_log, verify_lineage_chain
        entries = await get_lineage_log(client_id, limit)
        integrity = await verify_lineage_chain(client_id)
        return {"entries": entries, "integrity": integrity}
    except Exception as e:
        logger.error(f"Audit lineage fetch error: {e}")
        raise HTTPException(status_code=502, detail="Could not fetch the audit lineage log.")
@app.post("/api/v1/data/schema-audit", tags=["Ledger & Ingestion"])
async def run_schema_audit(client_id: str = Depends(enforce_budget_gate)):
    try:
        from backend.agents.data_engineer import analyze_schema_quality
        result = await asyncio.to_thread(analyze_schema_quality, client_id)
        return result
    except Exception as e:
        logger.error(f"Data Engineer Audit Error: {e}")
        raise HTTPException(status_code=502, detail="Schema audit failed. Please try again.")
@app.post("/api/v1/bi/summary", tags=["BI & Analytics"])
async def get_bi_summary(
    req: BISummaryRequest = BISummaryRequest(),
    user: AuthenticatedUser = Depends(enforce_budget_gate_for_user),
):
    try:
        from backend.agents.bi_engineer import generate_bi_summary
        result = await asyncio.to_thread(
            generate_bi_summary, user.client_id, req.query, None, user.user_id
        )
        return result
    except Exception as e:
        logger.error(f"BI Summary Error: {e}")
        raise HTTPException(status_code=502, detail="BI summary generation failed. Please try again.")
@app.post("/api/v1/predictive/forecast", tags=["Predictive & Forecasting"])
async def get_forecast(client_id: str = Depends(enforce_budget_gate)):
    try:
        from backend.agents.predictive_forecaster import generate_forecast
        result = await asyncio.to_thread(generate_forecast, client_id)
        return result
    except Exception as e:
        logger.error(f"Forecaster Error: {e}")
        raise HTTPException(status_code=502, detail="Forecast generation failed. Please try again.")


class ScenarioRequest(BaseModel):
    scenario_type: str = Field(..., description="One of: price_change_pct, new_hire_monthly_cost, churned_account_monthly_revenue")
    amount: float = Field(..., description="price_change_pct: a +/- percentage. new_hire_monthly_cost / churned_account_monthly_revenue: a dollar amount (sign ignored -- always treated as a cost/loss).")
    cash_reserves: Optional[float] = Field(None, ge=0, description="Optional override of the assumed cash reserve used for the runway figure. Omit to use the platform-wide assumed reserve (see the Assumption Ledger).")


@app.post("/api/v1/predictive/scenario", tags=["Predictive & Forecasting"])
async def run_scenario_endpoint(req: ScenarioRequest, client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        from backend.agents.scenario_modeler import run_scenario
        result = await run_scenario(client_id, req.scenario_type, req.amount, req.cash_reserves)
        if result.get("status") == "ERROR":
            raise HTTPException(status_code=400, detail="; ".join(result.get("insights", ["Invalid scenario request."])))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Scenario Modeler Error: {e}")
        raise HTTPException(status_code=502, detail="Scenario modeling failed. Please try again.")


@app.get("/api/v1/finance/forecast-accuracy", tags=["Predictive & Forecasting"])
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
@app.post("/api/v1/saas/strategy", tags=["SaaS Strategy"])
async def get_saas_strategy(client_id: str = Depends(enforce_budget_gate)):
    try:
        from backend.agents.saas_strategist import generate_strategy
        result = await asyncio.to_thread(generate_strategy, client_id)
        return result
    except Exception as e:
        logger.error(f"SaaS Strategist Error: {e}")
        raise HTTPException(status_code=502, detail="Strategy generation failed. Please try again.")
@app.post("/api/v1/bi/chart-suite", tags=["BI & Analytics"])
async def get_chart_suite(client_id: str = Depends(enforce_budget_gate)):
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
@app.post("/api/v1/finance/analytics-summary", tags=["BI & Analytics"])
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
@app.post("/api/v1/reports/stakeholder", tags=["Reports"])
async def get_stakeholder_report(client_id: str = Depends(enforce_budget_gate)):
    try:
        from backend.agents.report_generator import generate_stakeholder_report
        result = await asyncio.to_thread(generate_stakeholder_report, client_id)
        return result
    except Exception as e:
        logger.error(f"Report Generator Error: {e}")
        raise HTTPException(status_code=502, detail="Stakeholder report generation failed. Please try again.")


_EXPORT_MEDIA_TYPES = {"csv": "text/csv", "pdf": "application/pdf"}


# REP-01 (28 Aug 2026): the JSON endpoint above always existed; this is the
# first real, downloadable-file export -- CSV and PDF, both rendered from
# the exact same generate_stakeholder_report() dict the JSON endpoint
# returns (see backend/report_export.py's module docstring), so there is
# no second code path that could ever show different numbers than the
# JSON view of the same report. "Secure sharing and expiration" (REP-01's
# other named half -- a shareable external link) is NOT built here; see
# report_export.py's docstring for why that's a real policy call, not a
# mechanical one. enforce_budget_gate_for_user (not the plain client_id
# variant the JSON endpoint uses) is used here specifically so the export
# audit trail (REP-02) can record which user, not just which tenant,
# triggered each download.
@app.get("/api/v1/reports/stakeholder/export", tags=["Reports"])
async def export_stakeholder_report(
    format: str,
    user: AuthenticatedUser = Depends(enforce_budget_gate_for_user),
):
    if format not in _EXPORT_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported export format '{format}'. Use 'csv' or 'pdf'.")

    from backend.db_manager import log_report_export
    try:
        from backend.agents.report_generator import generate_stakeholder_report
        from backend.report_export import render_report_csv, render_report_pdf
        report = await asyncio.to_thread(generate_stakeholder_report, user.client_id)
        content = (
            render_report_csv(report) if format == "csv"
            else render_report_pdf(report, user.client_id)
        )
    except Exception as e:
        logger.error(f"Report export error ({format}): {e}")
        await log_report_export(user.client_id, user.user_id, "stakeholder", format, "ERROR")
        raise HTTPException(status_code=502, detail="Report export failed. Please try again.")

    await log_report_export(user.client_id, user.user_id, "stakeholder", format, "SUCCESS")
    safe_client_id = "".join(c for c in user.client_id if c.isalnum() or c in "-_")
    filename = f"stakeholder_report_{safe_client_id}_{datetime.utcnow().strftime('%Y%m%d')}.{format}"
    return Response(
        content=content,
        media_type=_EXPORT_MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v1/reports/export-history", tags=["Reports"])
async def get_report_export_history_endpoint(
    limit: int = 50,
    user: AuthenticatedUser = Depends(require_role("owner", "admin")),
):
    # REP-02: read side of the export audit trail. Owner/admin-only --
    # unlike the export endpoint itself (any authenticated tenant member
    # can download their own copy of the report), seeing WHO on the team
    # downloaded it is scoped the same way other cross-member visibility
    # already is elsewhere (e.g. the platform metrics endpoints).
    from backend.db_manager import get_report_export_history
    history = await get_report_export_history(user.client_id, limit)
    return {"exports": history}


class TelemetryScoutRequest(BaseModel):
    # Real, user-supplied sample from an external API/webhook -- the same
    # shape /api/search already accepts (see SearchRequest.sample_payload)
    # and forwards to this exact agent via orchestrator.py's keyword
    # routing. This dedicated endpoint exists precisely because that route
    # requires guessing the right trigger phrase in a free-text query; a
    # tenant using this real UI entry point (TelemetryScoutCard.tsx) never
    # has to know the routing keywords at all.
    sample_payload: Union[str, dict, list] = Field(..., description="A representative JSON sample (object, or array of objects) from the external API/webhook to map.")
    query: str = Field("", max_length=2000, description="Optional context for the LLM commentary layer -- purely descriptive, never used to alter the deterministic schema mapping itself.")


@app.post("/api/v1/telemetry/map-schema", tags=["Telemetry & Metrics"])
async def map_external_telemetry_schema(req: TelemetryScoutRequest, client_id: str = Depends(enforce_budget_gate)):
    try:
        from backend.agents.external_telemetry_scout import execute_task
        result = await asyncio.to_thread(execute_task, client_id, req.query, req.sample_payload)
        if result.get("status") == "ERROR":
            # A real, expected validation outcome (malformed/empty JSON) --
            # not a server fault, so this stays a 400, not the 502 used
            # below for genuine agent/infra failures.
            raise HTTPException(status_code=400, detail="; ".join(result.get("insights", ["Invalid sample payload."])))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"External Telemetry Scout Error: {e}")
        raise HTTPException(status_code=502, detail="Schema mapping failed. Please try again.")


# ---------------------------------------------------------------------------
# Track 3: persistent vector RAG knowledge base (backend/app/core/rag.py).
# Real embeddings, real Qdrant persistence, tenant-scoped on every call.
# ---------------------------------------------------------------------------

KNOWLEDGE_MAX_UPLOAD_BYTES = int(os.environ.get("EIVANTA_KNOWLEDGE_MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
KNOWLEDGE_SUPPORTED_EXTENSIONS = {".txt", ".pdf"}


def _extract_knowledge_text(file_path: str, ext: str) -> str:
    """
    Plain TEXT extraction for the knowledge base -- deliberately separate
    from db_manager's PDF TABLE extraction (Track 3 ingestion uses
    pdfplumber's extract_tables() for structured ledger rows; a policy/SOP
    document is prose, so this uses extract_text() per page instead).
    """
    if ext == ".txt":
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError as e:
            raise HTTPException(status_code=400, detail=f"This .txt file's encoding could not be read ({e}). Try re-saving as UTF-8.")
    if ext == ".pdf":
        try:
            import pdfplumber
        except ImportError:
            raise HTTPException(status_code=503, detail="PDF text extraction requires 'pdfplumber'. Run: pip install -r requirements.txt")
        try:
            with pdfplumber.open(file_path) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"This PDF could not be read: {e}.")
        text = "\n\n".join(p for p in pages if p.strip())
        if not text.strip():
            raise HTTPException(
                status_code=400,
                detail="No text could be extracted from this PDF -- it's likely a scanned/image-only PDF (OCR isn't supported yet).",
            )
        return text
    raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(KNOWLEDGE_SUPPORTED_EXTENSIONS))}.")


@app.post("/api/v1/knowledge/upload", tags=["Knowledge Base"])
async def upload_knowledge_document(
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(require_role("owner", "admin", "member")),
):
    client_id = user.client_id
    safe_filename = Path(file.filename or "document.txt").name
    ext = Path(safe_filename).suffix.lower()
    if ext not in KNOWLEDGE_SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext or '(none)'}'. Supported: {', '.join(sorted(KNOWLEDGE_SUPPORTED_EXTENSIONS))}.",
        )

    # SEC-03 SAST (28 Aug 2026, bandit B108): see the matching comment on
    # the ledger-upload endpoint above -- same fix, same reasoning.
    temp_dir = Path("/tmp/eivanta_knowledge")  # nosec B108 -- locked to 0700 immediately below, unconditionally, every request
    temp_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(temp_dir, 0o700)
    file_path = temp_dir / f"{client_id}_{uuid.uuid4().hex}_{safe_filename}"
    bytes_written = 0
    try:
        with open(file_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > KNOWLEDGE_MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds maximum allowed size.")
                buffer.write(chunk)

        text = _extract_knowledge_text(str(file_path), ext)

        from backend.app.core.rag import add_document
        doc_id = uuid.uuid4().hex
        chunk_count = await asyncio.to_thread(add_document, client_id, doc_id, safe_filename, text)
        return {"status": "SUCCESS", "doc_id": doc_id, "filename": safe_filename, "chunk_count": chunk_count}
    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Knowledge base upload blocked by configuration: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Knowledge base upload error: {e}")
        raise HTTPException(status_code=502, detail="Document indexing failed. Please try again.")
    finally:
        if file_path.exists():
            file_path.unlink()


class KnowledgeQueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=20)


@app.post("/api/v1/knowledge/query", tags=["Knowledge Base"])
async def query_knowledge_document(req: KnowledgeQueryRequest, client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        from backend.app.core.rag import query_knowledge_base
        results = await asyncio.to_thread(query_knowledge_base, client_id, req.query, req.limit)
        return {"query": req.query, "results": results}
    except Exception as e:
        logger.error(f"Knowledge base query error: {e}")
        raise HTTPException(status_code=502, detail="Knowledge base search failed. Please try again.")


@app.get("/api/v1/knowledge/documents", tags=["Knowledge Base"])
async def list_knowledge_documents(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        from backend.app.core.rag import list_documents
        docs = await asyncio.to_thread(list_documents, client_id)
        return {"documents": docs}
    except Exception as e:
        logger.error(f"Knowledge base list error: {e}")
        raise HTTPException(status_code=502, detail="Could not load knowledge base documents.")


@app.delete("/api/v1/knowledge/documents/{doc_id}", tags=["Knowledge Base"])
async def delete_knowledge_document(doc_id: str, user: AuthenticatedUser = Depends(require_role("owner", "admin", "member"))):
    try:
        from backend.app.core.rag import delete_document
        await asyncio.to_thread(delete_document, user.client_id, doc_id)
        return {"status": "SUCCESS"}
    except Exception as e:
        logger.error(f"Knowledge base delete error: {e}")
        raise HTTPException(status_code=502, detail="Could not delete this document.")
