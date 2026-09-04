"""
QA-05: chaos / agent-dropout tests. Before this file, nothing in
backend/tests/ deliberately injected a real failure into a routed agent's
own call and verified the platform degrades gracefully -- every other
orchestrator test (test_orchestrator_integration.py) exercises success
paths and real "no data yet" paths, never a genuine exception raised
mid-execution. Investigated directly (grep + Read, not assumed) before
writing anything:

  - `grep -rn "asyncio.wait_for\\|timeout=" main.py agents/orchestrator.py`
    returned zero matches: no request-level timeout backstop existed
    anywhere in the agent-execution path. Only the OpenAI client itself
    (each agents/*.py's own AI_REQUEST_TIMEOUT_SECONDS=30, AI-03) bounded
    an individual LLM call -- nothing bounded the whole request if that
    assumption were ever violated.
  - When an execute_* node's underlying agent call raises,
    state["results"][agent_name] is never populated, state["errors"]
    correctly captures the real exception text, but route_query()'s
    returned dict never included state["errors"] at all -- the caller only
    ever saw the fully generic string "No result was produced by the
    routed agent.", regardless of which agent failed or why. Confirmed
    against frontend/components/CognitiveSearchBar.tsx: it surfaces
    synthesized_insight verbatim as the user-facing error, so this generic
    string was the ENTIRE diagnostic value ever reaching a real user or an
    on-call engineer reading a support ticket.
  - backend/agent_registry.py's health-status/dropout-detection mechanism
    had zero direct test coverage (confirmed via
    `grep -rln "agent_registry" tests/*.py` returning nothing before this
    file).

Two real, contained fixes shipped alongside this test file (see
backend/main.py's SEARCH_REQUEST_TIMEOUT_SECONDS and
backend/agents/orchestrator.py's _summarize_result):

  1. /api/search now wraps both the Ops Shield threat check and
     route_query() in asyncio.wait_for(), returning an honest HTTP 504
     instead of hanging indefinitely. Deliberately disclosed, not silently
     assumed away: asyncio.wait_for() cancels the AWAITING coroutine, not
     the underlying asyncio.to_thread() worker thread itself -- Python's
     thread pool has no forced-cancellation mechanism, so a genuinely stuck
     worker keeps running in the background after the 504 is returned.
     This backstop's real guarantee is narrower than "kills the hang": the
     calling client gets a bounded, honest response, not that server-side
     resources are reclaimed.
  2. route_query()'s fallback message now names the specific agent that
     failed ("The 'X' agent could not complete this request due to an
     internal error...") instead of a fully generic string -- WITHOUT
     leaking raw exception text to the client (same non-leaking posture as
     ops_shield's own generic error responses; deliberate, not an
     oversight).

Five layers of coverage below:

  1. Parametrized failure injection for each of the 8 routed agents:
     proves graceful ERROR handling (no crash, no 500 propagating out of
     route_query itself), confidence_score 0.0, the new agent-naming fix,
     no raw exception leakage, and a real ERROR row landing in
     task_telemetry (not just an in-memory flag).
  2. A real timeout-backstop proof through the actual HTTP endpoint, using
     a monkeypatched test-scale timeout (never any real production value)
     so the test stays fast.
  3. Concurrent-request tenant isolation: one tenant's request is forced to
     fail while a different tenant's concurrent request succeeds, proving
     no cross-tenant state leakage through the shared compiled graph.
  4. Real DB-lock contention: many concurrent task_telemetry writes (the
     exact same log_task_execution() every execute_* node calls) under
     db_manager's real process-wide lock, proving no row is lost and no
     corruption occurs under concurrency.
  5. backend/agent_registry.py: a real healthy-baseline check (every real
     agent module actually imports cleanly today) plus a real
     unhealthy-reporting proof (a module that fails to import is correctly
     reported DEGRADED, with the failure reason captured) -- both
     previously untested.
"""
import concurrent.futures
import time

import duckdb
import pytest

from backend.agents import ops_shield, orchestrator


# ---------------------------------------------------------------------------
# Shared fixture: a real, isolated, empty tenant with BOTH the ledger
# schema (init_db) and the telemetry schema (init_telemetry_schema)
# created -- the latter is what every execute_* node's own
# log_task_execution() call writes into, and it is NOT created by init_db()
# alone (confirmed by reading db_manager.py directly: it's a separate
# function, imported and called by main.py's own startup, not init_db()).
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_tenant(isolated_db):
    import asyncio
    asyncio.run(isolated_db.init_db())
    asyncio.run(isolated_db.init_telemetry_schema())
    return "CLI-QA05-CHAOS-TEST"


def _latest_telemetry_status(isolated_db, agent_name: str):
    conn = duckdb.connect(isolated_db.DB_PATH)
    try:
        row = conn.execute(
            "SELECT status FROM task_telemetry WHERE agent_name = ? ORDER BY task_id DESC LIMIT 1",
            [agent_name],
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Layer 1: parametrized failure injection for each of the 8 routed agents.
# query values are the SAME grounded phrasings test_orchestrator_integration
# .py already proves route correctly -- reused here rather than re-guessed,
# so a routing regression would fail that file first, not silently corrupt
# this one's agent_name assertions.
# ---------------------------------------------------------------------------

CHAOS_AGENTS = [
    ("virtual_cfo", "Give me the executive briefing",
     "backend.agents.virtual_cfo", "generate_cfo_briefing"),
    ("data_engineer", "Run a schema audit on our pipeline",
     "backend.agents.data_engineer", "analyze_schema_quality"),
    ("bi_engineer", "What's the KPI variance on this dashboard?",
     "backend.agents.bi_engineer", "generate_bi_summary"),
    ("predictive_forecaster", "What's our revenue forecast for next quarter?",
     "backend.agents.predictive_forecaster", "generate_forecast"),
    ("saas_strategist", "How should we think about competitive pricing strategy?",
     "backend.agents.saas_strategist", "generate_strategy"),
    ("report_generator", "Export a stakeholder report as a PDF",
     "backend.agents.report_generator", "generate_stakeholder_report"),
    ("bi_visualization_architect", "Show me a chart visualizing revenue over time",
     "backend.agents.bi_visualization_architect", "execute_task"),
    ("external_telemetry_scout", "Can you flatten this external telemetry webhook payload?",
     "backend.agents.external_telemetry_scout", "execute_task"),
]


@pytest.mark.parametrize("agent_name,query,module_path,func_name", CHAOS_AGENTS)
def test_each_routed_agent_fails_gracefully_when_its_underlying_call_raises(
    empty_tenant, isolated_db, monkeypatch, agent_name, query, module_path, func_name
):
    import importlib
    module = importlib.import_module(module_path)

    injected_message = f"chaos-injected failure inside {agent_name}'s own call"

    def _boom(*args, **kwargs):
        raise RuntimeError(injected_message)

    monkeypatch.setattr(module, func_name, _boom)

    # The whole point: route_query() itself must never raise, no matter
    # which downstream agent blows up.
    result = orchestrator.route_query(query=query, client_id=empty_tenant)

    assert result["agent_breakdown"][0]["agent_name"] == agent_name
    assert result["status"] == "ERROR"
    # No fabricated confidence in a response that couldn't actually answer.
    assert result["confidence_score"] == 0.0
    # The fix: the failing agent is named...
    assert f"'{agent_name}'" in result["synthesized_insight"]
    assert "internal error" in result["synthesized_insight"].lower()
    # ...but the raw exception text is never leaked to the caller.
    assert injected_message not in result["synthesized_insight"]
    assert injected_message not in str(result["agent_breakdown"][0]["output_summary"])

    # A real ERROR row landed in task_telemetry -- not just an in-memory
    # flag that happens to look right in this one response.
    assert _latest_telemetry_status(isolated_db, agent_name) == "ERROR"


def test_chaos_agent_list_covers_every_real_graph_node_exactly_once():
    # Pins this file's own coverage against orchestrator.GRAPH_NODE_NAMES --
    # if a 9th agent is ever wired into the graph, this fails loudly instead
    # of this file silently going stale.
    covered = {row[0] for row in CHAOS_AGENTS}
    assert covered == orchestrator.GRAPH_NODE_NAMES
    assert len(CHAOS_AGENTS) == len(orchestrator.GRAPH_NODE_NAMES)


# ---------------------------------------------------------------------------
# Layer 2: the real request-level timeout backstop, through the actual
# /api/search HTTP endpoint. SEARCH_REQUEST_TIMEOUT_SECONDS is monkeypatched
# to a tiny test-scale value -- never any real production number -- so
# these stay fast; the injected "slow" calls sleep only slightly longer
# than that tiny timeout.
# ---------------------------------------------------------------------------

def test_search_endpoint_default_timeout_constant_exceeds_the_openai_client_timeout():
    # Sanity-checks the real, shipped default (not a test-only value):
    # deliberately larger than any single agent's own
    # AI_REQUEST_TIMEOUT_SECONDS (30s, AI-03) to leave real room for
    # ops_shield's own check plus the routed agent's own DB work around its
    # LLM call.
    import backend.main as main_module
    from backend.agents.virtual_cfo import AI_REQUEST_TIMEOUT_SECONDS

    assert main_module.SEARCH_REQUEST_TIMEOUT_SECONDS > AI_REQUEST_TIMEOUT_SECONDS


def test_ops_shield_call_that_hangs_returns_a_real_504_not_an_indefinite_hang(client, auth_headers, monkeypatch):
    import backend.main as main_module

    monkeypatch.setattr(main_module, "SEARCH_REQUEST_TIMEOUT_SECONDS", 0.05)

    def _slow_analyze_threat(client_id, payload):
        time.sleep(0.3)
        return {"status": "SECURE", "reason": ""}

    monkeypatch.setattr(ops_shield, "analyze_threat", _slow_analyze_threat)

    resp = client.post("/api/search", json={"query": "what is my revenue?"}, headers=auth_headers)

    assert resp.status_code == 504
    assert resp.json()["detail"] == "Security check timed out. Please try again."


def test_route_query_call_that_hangs_returns_a_real_504_not_an_indefinite_hang(client, auth_headers, monkeypatch):
    import backend.main as main_module

    monkeypatch.setattr(main_module, "SEARCH_REQUEST_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(ops_shield, "analyze_threat", lambda client_id, payload: {"status": "SECURE", "reason": ""})

    def _slow_route_query(*args, **kwargs):
        time.sleep(0.3)
        return {"status": "COMPLETE", "synthesized_insight": "should never be seen", "agent_breakdown": [], "confidence_score": 1.0}

    monkeypatch.setattr(orchestrator, "route_query", _slow_route_query)

    resp = client.post("/api/search", json={"query": "what is my revenue?"}, headers=auth_headers)

    assert resp.status_code == 504
    assert resp.json()["detail"] == "Search routing timed out. Please try again."
    assert "should never be seen" not in resp.text


def test_a_fast_secure_request_is_unaffected_by_the_new_timeout_backstop(client, auth_headers, monkeypatch):
    # The backstop must never fire on a genuinely fast, real call --
    # this is the same real end-to-end path
    # test_ops_shield_adversarial.py's test_secure_verdict_passes_through_
    # to_route_query already proves, re-asserted here specifically to pin
    # down that adding a timeout didn't change the fast-path status code.
    monkeypatch.setattr(ops_shield, "analyze_threat", lambda client_id, payload: {"status": "SECURE", "reason": ""})
    canned = {"status": "COMPLETE", "synthesized_insight": "Revenue is up.", "agent_breakdown": [], "confidence_score": 1.0}
    monkeypatch.setattr(orchestrator, "route_query", lambda *a, **kw: canned)

    resp = client.post("/api/search", json={"query": "what is my revenue?"}, headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == canned


# ---------------------------------------------------------------------------
# Layer 3: concurrent-request tenant isolation -- one tenant's request is
# forced to fail while a DIFFERENT tenant's concurrent request, routed to a
# DIFFERENT (real, unpatched) agent, succeeds. Proves the shared compiled
# LangGraph app_graph (one module-level object, invoked from many threads
# via main.py's real asyncio.to_thread pattern) carries no state across
# concurrent invocations for different tenants.
# ---------------------------------------------------------------------------

def test_one_tenants_forced_failure_never_contaminates_a_concurrent_tenants_success(isolated_db, monkeypatch):
    import asyncio
    asyncio.run(isolated_db.init_db())
    asyncio.run(isolated_db.init_telemetry_schema())

    failing_tenant = "CLI-QA05-CHAOS-FAIL"
    ok_tenant = "CLI-QA05-CHAOS-OK"

    def _boom(*args, **kwargs):
        raise RuntimeError("chaos: data_engineer forced down for this test")

    import backend.agents.data_engineer as data_engineer_module
    monkeypatch.setattr(data_engineer_module, "analyze_schema_quality", _boom)

    def _run_failing():
        return orchestrator.route_query(query="Run a schema audit on our pipeline", client_id=failing_tenant)

    def _run_ok():
        # Routes to virtual_cfo (unpatched, real call) -- a genuinely empty
        # tenant reaches the real NO_DATA success path with zero network
        # calls, same as test_orchestrator_integration.py's own
        # test_route_query_empty_tenant_reaches_real_no_data_response.
        return orchestrator.route_query(query="Give me the executive briefing", client_id=ok_tenant)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        fail_future = pool.submit(_run_failing)
        ok_future = pool.submit(_run_ok)
        fail_result = fail_future.result(timeout=30)
        ok_result = ok_future.result(timeout=30)

    assert fail_result["agent_breakdown"][0]["agent_name"] == "data_engineer"
    assert fail_result["status"] == "ERROR"
    assert fail_result["confidence_score"] == 0.0

    assert ok_result["agent_breakdown"][0]["agent_name"] == "virtual_cfo"
    assert ok_result["status"] != "ERROR"
    # The failing tenant's agent name/error text must never bleed into the
    # other tenant's response.
    assert "data_engineer" not in ok_result["synthesized_insight"]
    assert "chaos: data_engineer" not in ok_result["synthesized_insight"]


# ---------------------------------------------------------------------------
# Layer 4: real DB-lock contention on task_telemetry -- the exact table and
# write path (log_task_execution) every execute_* node calls on every real
# request, hammered concurrently under db_manager's real process-wide lock.
# ---------------------------------------------------------------------------

def test_concurrent_telemetry_writes_under_lock_contention_lose_no_rows(empty_tenant, isolated_db):
    import asyncio

    write_count = 24

    def _write_one(i: int):
        status = "COMPLETE" if i % 2 == 0 else "ERROR"
        asyncio.run(isolated_db.log_task_execution(f"chaos-contention-agent-{i % 4}", status, 0.01))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_write_one, range(write_count)))

    conn = duckdb.connect(isolated_db.DB_PATH)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM task_telemetry WHERE agent_name LIKE 'chaos-contention-agent-%'"
        ).fetchone()[0]
        error_count = conn.execute(
            "SELECT COUNT(*) FROM task_telemetry WHERE agent_name LIKE 'chaos-contention-agent-%' AND status = 'ERROR'"
        ).fetchone()[0]
        complete_count = conn.execute(
            "SELECT COUNT(*) FROM task_telemetry WHERE agent_name LIKE 'chaos-contention-agent-%' AND status = 'COMPLETE'"
        ).fetchone()[0]
    finally:
        conn.close()

    # No row lost, none duplicated, no corruption of status values under
    # real concurrent lock contention.
    assert total == write_count
    assert error_count == write_count // 2
    assert complete_count == write_count // 2


# ---------------------------------------------------------------------------
# Layer 5: backend/agent_registry.py -- previously zero direct test
# coverage (confirmed via grep before writing this file).
# ---------------------------------------------------------------------------

def test_agent_registry_reports_healthy_when_every_real_agent_module_imports_cleanly():
    from backend import agent_registry as registry_module

    fresh = registry_module.AgentRegistry()
    active, total, statuses, failures = fresh.get_health_status()

    assert total == len(registry_module.EXPECTED_AGENTS)
    assert active == total
    assert failures == {}
    assert all(statuses.values())

    metrics = fresh.verify_mathematical_integrity()
    assert metrics["status"] == "HEALTHY"
    assert metrics["failed_count"] == 0
    assert metrics["integrity_success_ratio_pct"] == 100.0


def test_agent_registry_reports_degraded_and_captures_the_reason_when_a_module_fails_to_import(monkeypatch):
    from backend import agent_registry as registry_module

    bogus_module_path = "backend.agents.this_module_does_not_exist_qa05_chaos_test"
    monkeypatch.setattr(
        registry_module, "EXPECTED_AGENTS",
        list(registry_module.EXPECTED_AGENTS) + [bogus_module_path],
    )

    fresh = registry_module.AgentRegistry()
    active, total, statuses, failures = fresh.get_health_status()

    assert total == len(registry_module.EXPECTED_AGENTS)
    assert active == total - 1
    assert statuses["this_module_does_not_exist_qa05_chaos_test"] is False
    assert "this_module_does_not_exist_qa05_chaos_test" in failures
    # A real, useful import-failure reason was captured, not silently dropped.
    assert failures["this_module_does_not_exist_qa05_chaos_test"]

    metrics = fresh.verify_mathematical_integrity()
    assert metrics["status"] == "DEGRADED"
    assert metrics["failed_count"] == 1
    assert metrics["integrity_success_ratio_pct"] < 100.0
