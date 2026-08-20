import os
import json
import logging
from typing import Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

logger = logging.getLogger("nexusflow.orchestrator")

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

def route_query(query: str, client_id: str = "default_client") -> Dict[str, Any]:
    """
    Agent #00 (Orchestrator). Performs semantic intent routing across the swarm.
    """
    safe_query = str(query)[:500]
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")

    system_prompt = f"""
    You are Agent #00, the Master Orchestrator for NexusFlow Analytics.
    Tenant: {safe_client_id}
    
    Your task is to analyze the user's incoming cognitive query and route it to the optimal sub-agent:
    - Systems Analyst Agent #02 (data pipeline, schema audit, debugging)
    - BI Engineer Agent #05 (business intelligence, categorical charts, distribution)
    - Predictive Forecaster Agent #07 (trends, projections, forecasting)
    - Virtual CFO Agent #08 (financial metrics, gross margin, burn rate, runway)
    - SaaS Strategist Agent #10 (business strategy, optimization)

    You MUST respond in pure JSON using this exact structure:
    {{
      "agent": "Orchestrator Agent #00",
      "query": "{safe_query}",
      "routed_to": "<Target Sub-Agent Name & ID>",
      "confidence": 0.95,
      "action": "<Brief description of the routing rationale>",
      "status": "COMPLETED"
    }}
    """

    try:
        if not client:
            raise ValueError("OpenAI client not initialized.")
            
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Route this query: {safe_query}"}
            ],
            temperature=0.2
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Orchestrator routing error: {e}")
        # Intelligent keyword-based fallback routing
        q_lower = safe_query.lower()
        routed_target = "Virtual CFO Agent #08"
        if any(w in q_lower for w in ['schema', 'sql', 'pipeline', 'error']):
            routed_target = "Systems Analyst Agent #02"
        elif any(w in q_lower for w in ['chart', 'bi', 'distribution', 'visualization']):
            routed_target = "BI Engineer Agent #05"
        elif any(w in q_lower for w in ['forecast', 'predict', 'trend']):
            routed_target = "Predictive Forecaster Agent #07"

        return {
            "agent": "Orchestrator Agent #00",
            "query": safe_query,
            "routed_to": routed_target,
            "confidence": 0.88,
            "action": f"Fallback routing based on keyword analysis due to API exception: {str(e)}",
            "status": "COMPLETED_FALLBACK"
        }
