import json
from backend.agents import orchestrator, bi_visualization_architect

# ------------------------------------------------------------------------
# FIXES APPLIED (verified against the real, current backend/agents files
# via a live execution harness before delivery):
#
# 1. `orchestrator.route_query(client_id=..., user_query=...)` -- WRONG
#    KEYWORD. The real signature is
#    `route_query(query: str, client_id: str, session_id=None, sample_payload=None)`
#    -- the parameter is named `query`, not `user_query`. The original call
#    raised `TypeError: route_query() got an unexpected keyword argument
#    'user_query'` on its very first line -- reproduced and confirmed live
#    before writing this fix. Both calls below use the real parameter name.
#
# 2. `bi_engineer.generate_dashboard_config(client_id=..., data_context=...)`
#    -- DOES NOT EXIST. bi_engineer.py has no such function anywhere (its
#    real public entry point is `generate_bi_summary(client_id, query)`,
#    an NL-to-SQL / categorical-BI-summary tool, not a dashboard-config
#    generator) -- confirmed via `hasattr`, not assumption.
#
#    The function that actually produces a real chart/dashboard
#    recommendation from a tenant's live ledger data is
#    `bi_visualization_architect.execute_task(client_id, query)` -- it
#    returns a real `recommended_chart_type` + `recharts_config` grounded
#    in `db_manager.get_ledger_chart_context`. That's almost certainly what
#    this test originally meant to exercise (its own docstring says
#    "Generating Dashboard Configs"), so I've redirected the call there
#    rather than just deleting the test. Flagging this substitution
#    explicitly since it's an interpretation of stale intent, not a
#    mechanical rename -- if "dashboard config" was meant to be something
#    else entirely (a feature not yet built), let me know and I'll adjust.
# ------------------------------------------------------------------------

print("==================================================")
print("1. TESTING ORCHESTRATOR (#00) - Routing a Business Strategy Query")
print("==================================================")
route_1 = orchestrator.route_query(
    query="We are losing subscribers. How do we fix our retention strategy?",
    client_id="test_tenant"
)
print(json.dumps(route_1, indent=2))

print("\n==================================================")
print("2. TESTING ORCHESTRATOR (#00) - Routing a Technical Error")
print("==================================================")
route_2 = orchestrator.route_query(
    query="I'm getting a traceback error in the DuckDB ingestor.",
    client_id="test_tenant"
)
print(json.dumps(route_2, indent=2))

print("\n==================================================")
print("3. TESTING BI VISUALIZATION ARCHITECT (#0?) - Chart/Dashboard Config")
print("(replaces the original bi_engineer.generate_dashboard_config call,")
print(" which does not exist -- see note above)")
print("==================================================")
bi_res = bi_visualization_architect.execute_task(
    client_id="test_tenant",
    query="""
    Q3 Revenue: $120,000. Q4 Revenue: $155,000.
    Customer Complaints by Category: Shipping delays (45), Defective products (20), Poor customer service (15), Billing errors (5).
    """
)
print(json.dumps(bi_res, indent=2))
print("\n--- TESTS COMPLETE ---")
print(
    "\nNOTE: this file has no `def test_*` functions, so `pytest` will "
    "collect ZERO test items from it despite the test_ filename -- it is "
    "a manual diagnostic script meant to be read by eye, run directly with "
    "`python test_backbone.py`, not `pytest test_backbone.py`."
)
