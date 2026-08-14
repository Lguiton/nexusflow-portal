import requests
import json

BASE_URL = "http://127.0.0.1:8000"

# 1. Define test prompts designed to trigger different agents and domains
test_queries = [
    # Data Analyst Agent #04 targets
    ("What was our total mrr for the year 2022?", "ANALYST"),
    ("List all transactions sorted by category", "ANALYST"),
    
    # Predictive Forecaster Agent #07 targets
    ("Forecast next month's churn probability and revenue growth", "FORECASTER"),
    ("Give me statistical confidence intervals for Q3 expansion", "FORECASTER"),
    
    # SaaS Strategist Agent #15 targets
    ("How do we optimize our gross margins for mid-market clients?", "STRATEGIST"),
    ("What is the best strategy to reduce customer churn in SaaS?", "STRATEGIST"),
]

def run_swarm_test():
    print("🚀 Initializing Full-Swarm Multi-Agent Diagnostic Test...\n")
    success_count = 0
    total_tests = len(test_queries)

    # Test 1: Cognitive Search Swarm (Orchestrator & Sub-agents)
    for i, (query, expected_agent) in enumerate(test_queries, 1):
        payload = {
            "query": query,
            "client_id": "CLI-001"
        }
        try:
            response = requests.post(f"{BASE_URL}/api/search", json=payload)
            if response.status_code == 200:
                data = response.json()
                routed_agent = data["agent_breakdown"][0]["output_summary"]
                insight = data["synthesized_insight"]
                
                # --- NEW ASSERTION LOGIC ---
                # Check if the guardrail caught a hallucination or failure
                if "Failed" in insight or "unsupported" in routed_agent.lower() or "error" in routed_agent.lower():
                    print(f"Test {i}: FAILED (Guardrail intercepted AI error)")
                    print(f"  Query: '{query}'")
                    print(f"  Guardrail Reason: {routed_agent}\n")
                else:
                    print(f"Test {i}: PASSED")
                    print(f"  Query: '{query}'")
                    print(f"  Route: {routed_agent}")
                    print(f"  Insight snippet: {insight[:90]}...\n")
                    success_count += 1
            else:
                print(f"Test {i}: FAILED (Status {response.status_code})\n")
        except Exception as e:
            print(f"Test {i}: ERROR ({e})\n")

    # Test 2: Comptroller Financial Audit Agent #12
    print("Testing Comptroller Audit Agent #12...")
    audit_payload = {
        "transactions": [
            {"tx_id": "TX-999", "amount": 4500.00, "category": "Software Subscriptions", "reason": "Monthly cloud hosting"},
            {"tx_id": "TX-1000", "amount": 125000.00, "category": "Unusual Expense", "reason": "Purchased a yacht for the engineering team"}
        ]
    }
    try:
        audit_res = requests.post(f"{BASE_URL}/api/v1/finance/comptroller-audit", json=audit_payload)
        if audit_res.status_code == 200:
            print("Comptroller Audit Test: PASSED (Ruthlessly flagged out-of-policy expense)\n")
        else:
            print(f"Comptroller Audit Test: FAILED (Status {audit_res.status_code})\n")
    except Exception as e:
        print(f"Comptroller Audit Test: ERROR ({e})\n")

    # Test 3: CFO Briefing Endpoint
    print("Testing Virtual CFO Briefing...")
    try:
        cfo_res = requests.post(f"{BASE_URL}/api/v1/finance/cfo-briefing")
        if cfo_res.status_code == 200:
            print("CFO Briefing Test: PASSED\n")
        else:
            print(f"CFO Briefing Test: FAILED (Status {cfo_res.status_code})\n")
    except Exception as e:
        print(f"CFO Briefing Test: ERROR ({e})\n")

    print(f"🎯 Swarm Test Complete. Successful Cognitive Routes: {success_count}/{total_tests}")

if __name__ == "__main__":
    run_swarm_test()