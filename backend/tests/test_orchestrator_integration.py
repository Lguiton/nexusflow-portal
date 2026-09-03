"""
Real integration tests for backend/agents/orchestrator.py (the LangGraph
multi-agent router/dispatcher). Before this file, NOTHING in backend/tests/
exercised the orchestrator at all -- test_agent_endpoints_require_auth.py
only proves the HTTP auth gate runs before an agent-backed endpoint is
reached, and no test anywhere called router_node/route_query directly.

Three layers, each real (no business logic mocked):

1. `router_node` / `determine_route` -- the keyword-based dispatch table
   itself. Pure, deterministic, no DB, no network. Every route + the
   unmatched-query fallback is covered.

2. `route_query()` end-to-end through the REAL compiled LangGraph
   (`app_graph`), against a real (isolated, per-test) empty tenant. Several
   different routes are exercised this way with ZERO network calls needed
   at all: every downstream agent module's own real "no ledger rows yet"
   guard returns before it would ever build an OpenAI client, so this
   proves the full router -> graph node -> real agent function -> back
   through route_query()'s response-shaping wiring for real, without
   touching OpenAI.

3. One real success-path test with a seeded tenant (real ledger rows via
   the real ingest_csv_to_db, same as test_ingestion.py/test_db_manager_
   queries.py) where ONLY the OpenAI network boundary is stubbed (same
   spy-client pattern as tools/verify_byok_rollout.py) -- proving the
   whole pipeline, including a real LLM-shaped success response, actually
   flows back out of route_query() with the right confidence_score and
   agent_breakdown shape.
"""
import pytest

from backend.agents import orchestrator


# ---------------------------------------------------------------------------
# Layer 1: router_node / determine_route -- pure, no DB, no network.
# ---------------------------------------------------------------------------

def _routed_agent(query: str) -> str:
    state = {
        "client_id": "CLI-ROUTING-TEST",
        "query": query,
        "active_agent": "router",
        "results": {},
        "status": "PENDING",
        "errors": [],
        "connection_key": None,
        "sample_payload": None,
        "session_id": None,
        "conversation_history": [],
    }
    routed_state = orchestrator.router_node(state)
    assert orchestrator.determine_route(routed_state) == routed_state["active_agent"]
    return routed_state["active_agent"]


@pytest.mark.parametrize(
    "query,expected_agent",
    [
        ("Can you flatten this external telemetry webhook payload?", "external_telemetry_scout"),
        ("What's going on with our data ingestion pipeline schema?", "data_engineer"),
        ("Show me a chart visualizing revenue over time", "bi_visualization_architect"),
        ("Export a stakeholder report as a PDF", "report_generator"),
        ("What's our revenue forecast for next quarter?", "predictive_forecaster"),
        ("How should we think about competitive pricing strategy?", "saas_strategist"),
        ("What's the KPI variance on this dashboard?", "bi_engineer"),
    ],
)
def test_router_node_routes_each_keyword_category_correctly(query, expected_agent):
    assert _routed_agent(query) == expected_agent


# AI-01 (this pass): broader, real coverage per agent -- multiple realistic
# phrasings each, grounded in what that agent's own module actually does
# (read directly before picking these, not guessed), proving the keyword
# tuning claimed in orchestrator.py's own router_node comment actually
# holds rather than being asserted only for one phrasing per agent above.
@pytest.mark.parametrize(
    "query,expected_agent",
    [
        # external_telemetry_scout
        ("We need to map an external feed into the platform", "external_telemetry_scout"),
        ("Can you help me connect an external tool via webhook?", "external_telemetry_scout"),
        ("Here's a raw payload from a third party data source", "external_telemetry_scout"),
        # data_engineer
        ("Can you run a data quality audit on our warehouse?", "data_engineer"),
        ("I need to fix my data before it breaks the pipeline", "data_engineer"),
        ("Help me with column mapping and header repair on this csv upload", "data_engineer"),
        ("What's wrong with our duckdb schema?", "data_engineer"),
        # bi_visualization_architect
        ("Can you build a heatmap of this data?", "bi_visualization_architect"),
        ("I want an infographic showing our growth", "bi_visualization_architect"),
        ("Plot this on a line graph", "bi_visualization_architect"),
        # report_generator
        ("I need a csv export of this month's numbers", "report_generator"),
        ("Put together a board deck for the investors", "report_generator"),
        ("Can you print this out for the meeting?", "report_generator"),
        # predictive_forecaster
        ("What's our outlook for next year?", "predictive_forecaster"),
        ("Give me the projected revenue for next month", "predictive_forecaster"),
        ("I want a trend forecast for the coming months", "predictive_forecaster"),
        # saas_strategist
        ("How's our market share compared to competitors?", "saas_strategist"),
        ("What should our go-to-market approach be?", "saas_strategist"),
        ("Is our price point competitive?", "saas_strategist"),
        # bi_engineer
        ("How are our KPIs trending month over month?", "bi_engineer"),
        ("Compare to last month's dashboard numbers", "bi_engineer"),
        ("What's the year over year variance?", "bi_engineer"),
    ],
)
def test_router_node_covers_multiple_realistic_phrasings_per_agent(query, expected_agent):
    assert _routed_agent(query) == expected_agent


def test_router_node_no_longer_misroutes_a_generic_data_mention_to_data_engineer():
    """Regression test for the real over-routing bug this pass fixed: bare
    "data" used to be a data_engineer keyword, so any query merely
    containing the word "data" -- including a plain financial question --
    was misrouted away from virtual_cfo. This financial question mentions
    "data" but contains none of data_engineer's real (schema/pipeline/
    hygiene) keywords, and must fall through to the default instead."""
    assert _routed_agent("What data do we have available for this quarter?") == "virtual_cfo"


def test_router_node_routes_table_never_targets_the_four_structurally_excluded_specialists():
    """Pins down the "8 of 12" boundary documented in router_node's own
    comment: ops_shield and scenario_modeler must never appear as a routing
    target (they are reached by other real mechanisms -- a pre-routing
    security gate and a dedicated structured-parameter endpoint,
    respectively, not this keyword table), and neither the retired-in-code
    "ingestion_engine"/"schema_mapper" agent names (folded into
    db_manager.py, ARCH-01) can appear either, since no such module exists
    to route to."""
    routed_agent_names = {agent_name for agent_name, _keywords in orchestrator.ROUTING_TABLE}
    excluded = {"ops_shield", "scenario_modeler", "ingestion_engine", "schema_mapper"}
    assert routed_agent_names.isdisjoint(excluded)
    # And the 7 real explicit routes (+ the virtual_cfo default = 8) are
    # exactly what's wired into the compiled graph -- no route points at an
    # agent name the graph itself doesn't have a node for.
    assert routed_agent_names.issubset(orchestrator.GRAPH_NODE_NAMES)
    assert routed_agent_names | {"virtual_cfo"} == orchestrator.GRAPH_NODE_NAMES


def test_router_node_falls_back_to_virtual_cfo_for_unmatched_query():
    # No keyword from any route table matches this -- must fall back to the
    # documented default rather than raising or leaving active_agent unset.
    assert _routed_agent("How is the business doing overall?") == "virtual_cfo"


def test_router_node_matching_is_case_insensitive():
    # router_node lowercases the query before matching -- an all-caps query
    # containing the same keyword must route identically.
    assert _routed_agent("SHOW ME A FORECAST FOR NEXT QUARTER") == "predictive_forecaster"


def test_router_node_first_matching_route_wins_on_keyword_overlap():
    # "dashboard" (bi_engineer) appears after "chart"/"visualiz" (bi_visualization_architect)
    # in the routes list -- a query matching both must take the earlier
    # table entry, not the later one. This pins down real, order-dependent
    # behavior rather than leaving it implicit.
    assert _routed_agent("chart this on the dashboard") == "bi_visualization_architect"


# ---------------------------------------------------------------------------
# Layer 2: route_query() through the REAL compiled graph, real empty
# tenant, zero network calls (every routed agent's own no-data guard
# returns before ever building an OpenAI client).
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_tenant(isolated_db):
    """A real, isolated tenant with the real `ledgers` table created but
    zero rows in it -- init_db() is the same real schema-creation path
    main.py's own startup uses, not a hand-rolled substitute schema."""
    import asyncio
    asyncio.run(isolated_db.init_db())
    return "CLI-EMPTY-ORCH-TEST"


@pytest.mark.parametrize(
    "query,expected_agent",
    [
        ("Run a schema audit on our pipeline", "data_engineer"),
        ("What pricing strategy should we use?", "saas_strategist"),
        ("Give me the executive briefing", "virtual_cfo"),
    ],
)
def test_route_query_empty_tenant_reaches_real_no_data_response(empty_tenant, query, expected_agent):
    result = orchestrator.route_query(query=query, client_id=empty_tenant)

    assert result["agent_breakdown"][0]["agent_name"] == expected_agent
    # A genuinely empty tenant must produce a real NO_DATA-shaped answer,
    # reported honestly with zero confidence -- never a fabricated 1.0.
    assert result["confidence_score"] == 0.0
    assert "no ledger data" in result["synthesized_insight"].lower() or \
           "no ledger data" in str(result["agent_breakdown"][0]["output_summary"]).lower()
    assert result["status"] == "COMPLETE"


def test_route_query_returns_real_conversation_history_on_second_call(empty_tenant):
    # Track 4 conversational memory: route_query logs each turn under
    # session_id, and the NEXT call for the same session should see it via
    # get_conversation_history -- proving the real DB-backed history round
    # trip, not just that a value was passed in.
    session_id = "sess-orch-history-1"
    orchestrator.route_query(query="Give me the executive briefing", client_id=empty_tenant, session_id=session_id)

    history = orchestrator._sync_get_history(empty_tenant, session_id)
    roles = [turn.get("role") for turn in history]
    assert "user" in roles
    assert "assistant" in roles


# ---------------------------------------------------------------------------
# Layer 3: one real success path, with ONLY the OpenAI network boundary
# stubbed (same spy-client pattern as tools/verify_byok_rollout.py) --
# real seeded ledger data, real graph execution, real response shaping.
# ---------------------------------------------------------------------------

class _StubMessage:
    def __init__(self, content):
        self.content = content


class _StubChoice:
    def __init__(self, content):
        self.message = _StubMessage(content)


class _StubCompletion:
    def __init__(self, content):
        self.choices = [_StubChoice(content)]
        self.usage = None


class _StubChatCompletions:
    def __init__(self, content):
        self._content = content

    def create(self, *args, **kwargs):
        return _StubCompletion(self._content)


class _StubChat:
    def __init__(self, content):
        self.completions = _StubChatCompletions(content)


class _StubOpenAIClient:
    def __init__(self, content):
        self.chat = _StubChat(content)


def test_route_query_success_path_with_seeded_tenant_and_stubbed_openai_boundary(isolated_db, tmp_path, monkeypatch):
    import asyncio
    import json
    from backend.agents import virtual_cfo

    tenant = "CLI-ORCH-SUCCESS-TEST"
    csv_path = tmp_path / "orch_success_seed.csv"
    csv_path.write_text(
        "date,category,amount,description\n"
        "2026-06-01,Revenue,5000,seed\n"
        "2026-06-05,Hosting,-400,seed\n",
        encoding="utf-8",
    )
    asyncio.run(isolated_db.ingest_csv_to_db(str(csv_path), tenant, "orch_success_seed.csv"))

    canned_insight_text = "Runway looks healthy given current burn."
    canned_response = json.dumps({
        "metrics": {"gross_margin": 92.0, "burn_rate": 400.0, "cash_runway_months": 3750.0},
        "insights": [canned_insight_text, "Second insight.", "Third insight."],
    })

    # ONLY the OpenAI network boundary is stubbed -- everything else
    # (router_node, the compiled graph, generate_cfo_briefing's own real
    # DB query + revenue/COGS classification math) runs for real.
    monkeypatch.setattr(
        virtual_cfo, "get_openai_client_for_tenant_sync",
        lambda client_id, platform_api_key, timeout, max_retries: _StubOpenAIClient(canned_response),
    )

    result = orchestrator.route_query(query="Give me the executive briefing", client_id=tenant)

    assert result["agent_breakdown"][0]["agent_name"] == "virtual_cfo"
    assert result["confidence_score"] == 1.0
    assert result["status"] == "COMPLETE"
    assert canned_insight_text in str(result["agent_breakdown"][0]["output_summary"])
