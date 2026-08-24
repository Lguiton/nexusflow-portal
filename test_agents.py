import json
from backend.agents import saas_strategist, data_engineer

# ------------------------------------------------------------------------
# FIXES APPLIED (verified against the real, current backend/agents files
# via a live execution harness before delivery -- not just read by eye):
#
# 1. `from backend.agents import ... code_customizer` -- REMOVED. There is
#    no backend/agents/code_customizer.py anywhere in the real project;
#    this import alone raised ImportError and crashed the whole script
#    before test #1 ever ran. Unlike data_engineer.py's
#    diagnose_and_propose_fix (see #3 below), I found no comment or git
#    history anywhere indicating this was ever built and then deliberately
#    retired -- it may be a still-planned agent that was never
#    implemented, or a stale reference to something renamed. Flagging this
#    explicitly rather than guessing: if Code Customizer is meant to exist,
#    it needs to be built before this test can cover it again.
#
# 2. `saas_strategist.execute_task(client_id=..., query=...)` -- WRONG.
#    The real, only public entry point is
#    `generate_strategy(client_id: str = "default_client")` -- no `query`
#    parameter exists on Agent #10 at all. Fixed to call the real function.
#
# 3. `data_engineer.diagnose_and_propose_fix(...)` -- REMOVED. The real
#    data_engineer.py contains an explicit comment recording why: it
#    implemented an LLM-driven code-diff generator with no test-gate or
#    branch-scoped-credential enforcement, contradicting the "no agent
#    writes or executes code" decision recorded across the architecture
#    docs. That's a real, already-made architecture decision (not one I'm
#    making now) -- so this test's call to it is dropped, not patched.
#
# 4. `code_customizer.execute_task(...)` (Bug Refactor test) -- REMOVED
#    along with the import (see #1).
# ------------------------------------------------------------------------

print("==================================================")
print("1. TESTING SAAS STRATEGIST (Agent #10)")
print("Generating tenant-grounded SaaS growth strategy...")
print("==================================================")
res1 = saas_strategist.generate_strategy(client_id="test_tenant_1")
print(json.dumps(res1, indent=2))

print("\n==================================================")
print("2. TESTING DATA ENGINEER (Agent #02) - Schema Quality")
print("Triggering pipeline and database analysis...")
print("==================================================")
res2 = data_engineer.analyze_schema_quality(client_id="test_tenant_1")
print(json.dumps(res2, indent=2))

print("\n--- TESTS COMPLETE ---")
print(
    "\nNOTE: this file has no `def test_*` functions, so `pytest` will "
    "collect ZERO test items from it despite the test_ filename -- it is "
    "a manual diagnostic script meant to be read by eye, run directly with "
    "`python test_agents.py`, not `pytest test_agents.py`. Worth deciding "
    "whether this should stay a manual script or be converted to real "
    "asserting pytest tests like swarm_test.py."
)
