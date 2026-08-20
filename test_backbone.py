import json
from backend.agents import orchestrator, bi_engineer

print("==================================================")
print("1. TESTING ORCHESTRATOR (#00) - Routing a Business Strategy Query")
print("==================================================")
route_1 = orchestrator.route_query(
    client_id="test_tenant", 
    user_query="We are losing subscribers. How do we fix our retention strategy?"
)
print(json.dumps(route_1, indent=2))

print("\n==================================================")
print("2. TESTING ORCHESTRATOR (#00) - Routing a Technical Error")
print("==================================================")
route_2 = orchestrator.route_query(
    client_id="test_tenant", 
    user_query="I'm getting a traceback error in the DuckDB ingestor."
)
print(json.dumps(route_2, indent=2))

print("\n==================================================")
print("3. TESTING BI ENGINEER (#05) - Generating Dashboard Configs")
print("==================================================")
bi_res = bi_engineer.generate_dashboard_config(
    client_id="test_tenant", 
    data_context="""
    Q3 Revenue: $120,000. Q4 Revenue: $155,000. 
    Customer Complaints by Category: Shipping delays (45), Defective products (20), Poor customer service (15), Billing errors (5).
    """
)
print(json.dumps(bi_res, indent=2))
print("\n--- TESTS COMPLETE ---")
