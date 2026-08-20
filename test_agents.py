import json
from backend.agents import saas_strategist, data_engineer, code_customizer

print("==================================================")
print("1. TESTING SAAS STRATEGIST (Agent #10)")
print("Triggering Six Sigma anomaly resolution...")
print("==================================================")
res1 = saas_strategist.execute_task(
    client_id="test_tenant_1", 
    query="Our labor costs spiked by 15% last week due to unexpected overtime."
)
print(json.dumps(res1, indent=2))

print("\n==================================================")
print("2. TESTING DATA ENGINEER (Agent #02) - Schema Quality")
print("Triggering pipeline and database analysis...")
print("==================================================")
res2 = data_engineer.analyze_schema_quality(client_id="test_tenant_1")
print(json.dumps(res2, indent=2))

print("\n==================================================")
print("3. TESTING DATA ENGINEER (Agent #02) - HITL Self-Healing")
print("Triggering strictly read-only code diagnosis...")
print("==================================================")
res3 = data_engineer.diagnose_and_propose_fix(
    client_id="test_tenant_1", 
    error_traceback="SyntaxError: expected ':'", 
    file_content="def calculate_margins() return total_rev - costs", 
    file_name="finance_utils.py"
)
print(json.dumps(res3, indent=2))

print("\n==================================================")
print("4. TESTING CODE CUSTOMIZER (Agent #02) - Bug Refactor")
print("Triggering strictly read-only bug refactor...")
print("==================================================")
res4 = code_customizer.execute_task(
    client_id="test_tenant_1", 
    query="Refactor this broken python code: def calculate() return 5"
)
print(json.dumps(res4, indent=2))
print("\n--- TESTS COMPLETE ---")
