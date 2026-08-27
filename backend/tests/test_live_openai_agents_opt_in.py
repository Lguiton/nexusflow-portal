"""
Real, LIVE-OpenAI-API smoke tests for the 8 BYOK-rolled-out agent
modules -- the migrated, assertion-based replacement for the four ad hoc
root-level diagnostic scripts this repo used to carry
(test_agents.py, test_backbone.py, test_cfo_direct.py,
test_db_manager_live.py): scripts with no `def test_*` functions, meant to
be run by hand with `python some_script.py` and read by eye, not collected
or asserted on by pytest at all.

test_db_manager_live.py's own real-DuckDB checks are fully superseded by
backend/tests/test_db_manager_queries.py (a real, assertion-based pytest
suite against the same db_manager.py functions) -- that script itself has
been retired, not migrated here.

The other three scripts' unique value was exercising REAL agent business
logic against a REAL, currently-billed OpenAI API call -- something
deliberately out of scope for the rest of backend/tests/ (see
tests/README.md's "What's deliberately NOT covered here"), and something
test_orchestrator_integration.py's own success-path test deliberately
stops short of too (it stubs the OpenAI network boundary so it can run in
every `pytest` invocation without a real API key or real cost). This file
is the intentional, explicitly opt-in home for that real-API layer:
skipped by default, so a bare `pytest backend/tests` never spends money or
needs a real key, and run only when BOTH of the following are true:

    EIVANTA_RUN_LIVE_OPENAI_TESTS=1
    OPENAI_API_KEY=<a real key>

    pytest backend/tests/test_live_openai_agents_opt_in.py -v

Every test seeds real ledger rows via the real ingest_csv_to_db (isolated
per-test DB, same as the rest of this suite) so each agent has real,
non-empty data to reason about, then asserts on the REAL response shape
each agent's own code contract promises -- not just "it didn't crash."
"""
import asyncio
import os

import pytest

_LIVE_ENABLED = os.environ.get("EIVANTA_RUN_LIVE_OPENAI_TESTS") == "1"
_REAL_KEY_PRESENT = bool(os.environ.get("OPENAI_API_KEY")) and not os.environ["OPENAI_API_KEY"].startswith(
    "sk-test-placeholder"
)

pytestmark = pytest.mark.skipif(
    not (_LIVE_ENABLED and _REAL_KEY_PRESENT),
    reason=(
        "Live-OpenAI agent tests are opt-in -- set EIVANTA_RUN_LIVE_OPENAI_TESTS=1 "
        "and a real OPENAI_API_KEY to run them. Skipped by default so the main "
        "suite never makes a real, billed API call."
    ),
)


@pytest.fixture
def seeded_tenant(isolated_db, tmp_path):
    """A real tenant with several months of real revenue/expense rows --
    enough for every agent under test here to have real data to reason
    about, and enough distinct months for predictive_forecaster-adjacent
    logic elsewhere in the suite (not exercised directly in this file)."""
    from tests.conftest import make_ledger_csv

    tenant = "CLI-LIVE-OPENAI-TEST"
    csv_path = make_ledger_csv(
        tmp_path,
        [
            "2026-04-05,Revenue,4000,seed",
            "2026-04-20,Software,-300,seed",
            "2026-05-05,Revenue,4200,seed",
            "2026-05-20,Software,-310,seed",
            "2026-06-05,Revenue,4500,seed",
            "2026-06-20,Software,-290,seed",
        ],
    )
    asyncio.run(isolated_db.ingest_csv_to_db(csv_path, tenant, "seed.csv"))
    return tenant


def test_virtual_cfo_generate_cfo_briefing_live(seeded_tenant):
    """Migrated from test_cfo_direct.py. Real DB-backed metrics plus a
    real OpenAI call; falls back to a template narrative if the LLM call
    itself fails, so this only asserts the metrics-and-shape contract that
    holds either way -- it does not assert on LLM-generated prose."""
    from backend.agents.virtual_cfo import generate_cfo_briefing

    result = generate_cfo_briefing(client_id=seeded_tenant)

    assert "metrics" in result
    assert set(result["metrics"].keys()) == {"gross_margin", "burn_rate", "cash_runway_months"}
    assert isinstance(result["insights"], list) and len(result["insights"]) > 0
    assert result["assumed_cash_reserves"] == 1500000.0


def test_saas_strategist_generate_strategy_live(seeded_tenant):
    """Migrated from test_agents.py. The real, only public entry point is
    generate_strategy(client_id) -- the original script's
    execute_task(client_id=..., query=...) call never existed on this
    agent (see this file's module docstring history in the delivered
    report for that correction)."""
    from backend.agents.saas_strategist import generate_strategy

    result = generate_strategy(client_id=seeded_tenant)

    assert result["status"] in ("OPTIMIZED", "FALLBACK")
    assert isinstance(result["strategies"], list) and len(result["strategies"]) > 0
    assert result["metrics"]["total_rows"] > 0


def test_data_engineer_analyze_schema_quality_live(seeded_tenant):
    """Migrated from test_agents.py."""
    from backend.agents.data_engineer import analyze_schema_quality

    result = analyze_schema_quality(client_id=seeded_tenant)

    assert result["status"] in ("OPTIMIZED",)
    assert isinstance(result["recommendations"], list) and len(result["recommendations"]) > 0
    assert result["metrics"]["total_rows"] > 0


def test_bi_visualization_architect_execute_task_live(seeded_tenant):
    """Migrated from test_backbone.py. The original script's
    bi_engineer.generate_dashboard_config(...) call never existed on any
    agent -- bi_visualization_architect.execute_task(client_id, query) is
    the real chart-recommendation entry point that actually reads live
    ledger data via db_manager.get_ledger_chart_context."""
    from backend.agents.bi_visualization_architect import execute_task

    result = execute_task(client_id=seeded_tenant, query="Show me a chart of revenue over time")

    assert result["status"] == "COMPLETED"
    assert "recommended_chart_type" in result
    assert "recharts_config" in result


def test_orchestrator_route_query_strategy_question_live(seeded_tenant):
    """Migrated from test_backbone.py's orchestrator.route_query() call,
    using the real (corrected) `query` keyword argument -- the original
    script's `user_query=` kwarg does not exist on the real signature."""
    from backend.agents import orchestrator

    result = orchestrator.route_query(
        query="We are losing subscribers. How do we fix our retention strategy?",
        client_id=seeded_tenant,
    )

    assert result["agent_breakdown"][0]["agent_name"] == "saas_strategist"
    assert result["status"] == "COMPLETE"
    assert result["confidence_score"] == 1.0


def test_orchestrator_route_query_cfo_briefing_live(seeded_tenant):
    """Migrated from test_cfo_direct.py's implicit intent (the original
    script called generate_cfo_briefing directly but never routed through
    the orchestrator at all despite testing "Agent #06" by name) -- this
    covers the same agent through the real router path instead."""
    from backend.agents import orchestrator

    result = orchestrator.route_query(query="Give me the executive briefing", client_id=seeded_tenant)

    assert result["agent_breakdown"][0]["agent_name"] == "virtual_cfo"
    assert result["status"] == "COMPLETE"
    assert result["confidence_score"] == 1.0
