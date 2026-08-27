"""
INT-01: Model Context Protocol (MCP) read-only analytics tool server.

Lets an external MCP-aware client (Claude Desktop, another workflow tool)
query ONE tenant's real analytics data over the network, authenticated by
a scoped API key (backend/api_keys.py), without any custom connector code.

Design choices made here, stated plainly rather than left implicit:

- Transport: Streamable HTTP (the current MCP standard for a remote/hosted
  server), mounted on this same FastAPI app at /mcp -- not a local stdio
  server. A tenant configures their MCP client with this server's URL plus
  their own scoped API key; nothing to install.
- Auth: a custom ASGI middleware in front of the MCP app, NOT the `mcp`
  SDK's built-in OAuth resource-server plumbing (mcp.server.auth). That
  machinery assumes a full OAuth authorization server with dynamic client
  registration and a published issuer_url -- real infrastructure this
  product doesn't have and doesn't need for "a customer's own tool calls
  its own tenant's data with a key it generated in Settings." A static
  bearer API key, validated against db_manager's api_keys table, is the
  right amount of mechanism for that -- see backend/api_keys.py for where
  a tenant creates/revokes one.
- Statelessness: stateless_http=True. Every tool call here is a single
  read-only query with no multi-turn tool session state to preserve, so
  there is no reason to hold a server-side session (and every reason not
  to, if this ever runs behind more than one backend instance).
- Scope: read-only, deliberately. No tool below can mutate a tenant's
  data -- upload, delete, category-suggestion-apply, budget/BYOK settings,
  etc. all stay REST-only, JWT-only, never reachable through an API key.
  A leaked MCP key's blast radius is exactly these seven read paths, never
  the mutating surface of the app.

Each tool call resolves its tenant from the API key the middleware already
validated (via a contextvar set once per request) -- never a client_id
argument the MCP client could supply itself, which would let one tenant's
key read another tenant's data just by passing a different id.
"""
import asyncio
import contextlib
import contextvars
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

try:
    from backend import db_manager
    from backend import assumptions as assumptions_module
    from backend import gaps as gaps_module
    from backend.agents import bi_engineer, predictive_forecaster
except ImportError:
    import db_manager
    import assumptions as assumptions_module
    import gaps as gaps_module
    from agents import bi_engineer, predictive_forecaster

logger = logging.getLogger("eivanta.mcp_server")

_tenant_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("mcp_tenant_client_id")


def _current_tenant() -> str:
    try:
        return _tenant_ctx.get()
    except LookupError:
        # Should be unreachable: ApiKeyAuthMiddleware sets this for every
        # request that reaches the MCP app at all. Fail loud, not with a
        # confusing downstream KeyError/None client_id.
        raise RuntimeError(
            "No authenticated tenant in context -- ApiKeyAuthMiddleware "
            "should have rejected this request before it reached a tool."
        )


async def _check_budget_or_raise() -> None:
    """
    Shared by the two LLM-backed tools below (bi_summary, forecast) --
    same real per-tenant monthly USD cap that already gates their REST
    equivalents (main.py's enforce_budget_gate). An MCP key must not be a
    way to bypass a cap a tenant set on themselves via the REST API.
    """
    client_id = _current_tenant()
    try:
        gate = await db_manager.check_budget_gate(client_id)
    except Exception as e:
        logger.error(f"Budget gate check failed for tenant '{client_id}' via MCP, allowing request: {e}")
        return
    if not gate.get("allowed", True):
        raise RuntimeError(
            f"Monthly AI usage cap reached (${gate['usage_usd']:.2f} of ${gate['cap_usd']:.2f}). "
            "Raise or remove the cap in Settings to continue."
        )


async def get_bi_summary(query: str = "") -> dict:
    """
    Ask a natural-language question about this tenant's financial ledger
    (BI Engineer agent). Leave query empty for a general summary. Costs a
    real LLM call, subject to this tenant's monthly AI budget cap if one
    is set.
    """
    client_id = _current_tenant()
    await _check_budget_or_raise()
    return await asyncio.to_thread(bi_engineer.generate_bi_summary, client_id, query)


async def get_forecast() -> dict:
    """
    Real revenue forecast for this tenant (Predictive Forecaster agent):
    projected revenue, growth rate, r-squared, and revenue-risk level.
    Returns an honest INSUFFICIENT_HISTORY state if the tenant doesn't yet
    have enough months of ledger history. Costs a real LLM call, subject
    to this tenant's monthly AI budget cap if one is set.
    """
    client_id = _current_tenant()
    await _check_budget_or_raise()
    return await asyncio.to_thread(predictive_forecaster.generate_forecast, client_id)


async def get_ledger_rows(
    category: Optional[str] = None,
    month: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 200,
) -> dict:
    """
    Drill down to the real ledger rows behind a category/month/date-range
    filter -- the same evidence-trail data the dashboard's Ledger Row
    Explorer shows. No LLM call; free to call as often as needed.
    """
    client_id = _current_tenant()
    return await db_manager.get_ledger_rows(
        client_id, category=category, month=month, limit=limit,
        date_from=date_from, date_to=date_to,
    )


async def get_kpi_summary() -> dict:
    """
    Headline finance KPIs for this tenant: total ledger amount and row
    count, current-month revenue, and real Monthly Recurring Revenue where
    available. No LLM call.

    Note: this composes the same two underlying db_manager calls as
    main.py's REST /api/v1/finance/kpi-summary endpoint rather than
    calling that endpoint's handler directly (FastAPI route handlers
    aren't meant to be invoked as plain functions outside a request) --
    kept as a small, deliberate duplication rather than a larger refactor
    of the working REST endpoint in this pass. Keys from mrr_summary are
    picked individually rather than spread with **mrr_summary -- a real
    bug caught in this module's own verification pass: mrr_summary has
    its own unrelated "revenue_month" key (the month MRR was computed
    for, null whenever mrr_available is False), which a blind spread
    silently overwrote this function's real current-calendar-month value
    with -- exactly the trap main.py's own endpoint avoids the same way.
    """
    from datetime import date as _date
    client_id = _current_tenant()
    context = await db_manager.get_ledger_chart_context(client_id)
    mrr_summary = await db_manager.get_mrr_summary(client_id)
    ledger_total_amount = round(
        sum(c["total_amount"] for c in context.get("category_breakdown", [])), 2
    )
    current_month_key = _date.today().strftime("%Y-%m")
    monthly_revenue = next(
        (m["total_amount"] for m in context.get("monthly_totals", []) if m["month"] == current_month_key),
        0.0,
    )
    return {
        "ledger_total_amount": ledger_total_amount,
        "ledger_row_count": context.get("row_count", 0),
        "monthly_revenue": monthly_revenue,
        "monthly_revenue_label": "Monthly Revenue",
        "revenue_month": current_month_key,
        "mrr": mrr_summary["mrr"],
        "mrr_available": mrr_summary["mrr_available"],
        "mrr_note": mrr_summary["note"],
    }


async def get_mrr_summary() -> dict:
    """
    Real Monthly Recurring Revenue for this tenant, computed only from
    transactions explicitly flagged recurring on upload. mrr_available is
    false and mrr is null if this tenant has never provided that flag --
    never a silently backfilled or guessed number. No LLM call.
    """
    client_id = _current_tenant()
    return await db_manager.get_mrr_summary(client_id)


async def get_assumptions() -> dict:
    """
    The Assumption Ledger: real numeric constants and methodology notes
    every calculation on this dashboard depends on (assumed cash reserves,
    forecast minimum-history threshold, MRR definition, and more) -- read
    live from the code that uses them, not a separately maintained
    description. Platform-wide, not tenant-specific. No LLM call.
    """
    return assumptions_module._build_assumptions()


async def get_known_gaps() -> dict:
    """
    The Known Gaps panel: real, currently-true limitations for this
    specific tenant (e.g. "no data yet", "MRR not available yet",
    "forecast needs N more months of history") -- computed from cheap,
    non-LLM signals, not a static disclaimer. No LLM call.
    """
    client_id = _current_tenant()
    return await gaps_module.get_known_gaps(client_id)


async def _send_json_error(send, status: int, message: str) -> None:
    import json as _json
    body = _json.dumps({"error": message}).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class ApiKeyAuthMiddleware:
    """
    Raw ASGI middleware, not a Starlette/FastAPI dependency -- this wraps
    the MCP server's own Streamable HTTP ASGI app directly (see
    create_mcp_asgi_app below), so it has to speak ASGI itself rather than
    relying on request-object conveniences that only exist inside a
    Starlette route.

    Every request must carry `Authorization: Bearer <api_key>` where
    <api_key> is a live (unrevoked) key from backend/api_keys.py. On
    success, the resolved tenant client_id is stashed in _tenant_ctx for
    the duration of this one request -- every tool function above reads it
    from there, never from anything the MCP client itself supplies.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth_header = headers.get(b"authorization", b"").decode("latin-1")
        if not auth_header.startswith("Bearer "):
            await _send_json_error(
                send, 401,
                "Missing or malformed Authorization header. "
                "Provide 'Authorization: Bearer <your Eivanta API key>'.",
            )
            return

        raw_key = auth_header[len("Bearer "):].strip()
        try:
            resolved = await db_manager.get_client_id_for_api_key(raw_key)
        except Exception as e:
            logger.error(f"API key lookup failed for MCP request: {e}")
            await _send_json_error(send, 502, "Could not validate API key right now.")
            return

        if resolved is None:
            await _send_json_error(send, 401, "Invalid or revoked API key.")
            return

        token = _tenant_ctx.set(resolved["client_id"])
        try:
            await self.app(scope, receive, send)
        finally:
            _tenant_ctx.reset(token)


def _build_mcp() -> FastMCP:
    """
    A fresh FastMCP instance every call, deliberately NOT a module-level
    singleton -- its Streamable HTTP session manager can only ever have
    .run() called once per instance (confirmed the hard way in this
    module's own verification pass: a second FastAPI app instance sharing
    one already-started session manager raises "can only be called once
    per instance"). That would bite any process that assembles the app
    more than once -- a test suite reloading backend.main per test
    (exactly how backend/tests/conftest.py's `app` fixture works), a dev
    server's --reload, or a future multi-app-instance deployment -- so
    each app assembly gets its own tools-registered-fresh instance rather
    than reusing one created at import time.
    """
    mcp = FastMCP(
        name="Eivanta Analytics (Read-Only)",
        instructions=(
            "Read-only analytics tools for one Eivanta tenant, scoped to "
            "whichever API key authenticated this connection. No tool here "
            "can modify data -- ledger uploads, deletes, and settings changes "
            "all require the real Eivanta dashboard."
        ),
        stateless_http=True,
        streamable_http_path="/",
    )
    for fn in (
        get_bi_summary, get_forecast, get_ledger_rows, get_kpi_summary,
        get_mrr_summary, get_assumptions, get_known_gaps,
    ):
        mcp.add_tool(fn)
    return mcp


def create_mcp_asgi_app_and_lifespan():
    """
    What main.py calls once per app assembly (see main.py's own comment at
    the call site): returns (mcp_asgi_app, mcp_lifespan) bound to the SAME
    fresh FastMCP instance, so the asgi app's session manager and the
    lifespan that starts it are always a matched pair -- never one fresh
    instance's asgi app paired with a different instance's (already-used,
    or not-yet-started) session manager.
    """
    mcp = _build_mcp()
    mcp_asgi_app = ApiKeyAuthMiddleware(mcp.streamable_http_app())

    @contextlib.asynccontextmanager
    async def mcp_lifespan():
        """
        The Streamable HTTP transport's session manager runs its own
        internal task group and must be started via this context manager
        BEFORE any request reaches mcp_asgi_app, or every request 500s
        with "Task group is not initialized" -- confirmed the hard way in
        this module's own verification pass. main.py composes this into
        its top-level FastAPI lifespan since mounting a sub-app with
        `app.mount()` alone does NOT propagate the sub-app's lifespan
        automatically.
        """
        async with mcp.session_manager.run():
            yield

    return mcp_asgi_app, mcp_lifespan
