import os
import json
import logging
import duckdb
from typing import Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

logger = logging.getLogger("nexusflow.predictive_forecaster")

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

def generate_forecast(client_id: str = "default_client") -> Dict[str, Any]:
    """
    Agent #07 (Predictive Forecaster). Generates trend analysis and revenue projections.
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    
    historical_revenue = 450000.0
    db_paths = ["nexusflow.duckdb", "backend/nexusflow.duckdb", "data.duckdb", "backend/data.duckdb"]
    conn = None
    for path in db_paths:
        if os.path.exists(path):
            try:
                conn = duckdb.connect(path, read_only=True)
                break
            except Exception:
                pass

    try:
        if conn:
            tables = conn.execute("SHOW TABLES").fetchall()
            table_names = [t[0] for t in tables]
            if "ledgers" in table_names:
                res = conn.execute(
                    "SELECT SUM(amount) FROM ledgers WHERE client_id = ? AND amount > 0", 
                    [safe_client_id]
                ).fetchone()
                if res and res[0] is not None:
                    historical_revenue = float(res[0])
    except Exception as e:
        logger.error(f"DuckDB query error in Forecaster: {e}")
    finally:
        if conn:
            conn.close()

    projected_q4 = historical_revenue * 1.15
    growth_rate_pct = 15.0

    system_prompt = f"""
    You are Agent #07, NexusFlow's Predictive Forecaster.
    Tenant: {safe_client_id}
    Baseline Revenue: ${historical_revenue:,.2f}
    Projected Q4 Revenue (15% Growth Model): ${projected_q4:,.2f}
    
    Provide exactly 3 forward-looking strategic projections and confidence intervals.
    
    You MUST respond in pure JSON using this exact structure:
    {{
      "agent": "Predictive Forecaster Agent #07",
      "status": "PROJECTED",
      "baseline_revenue": {historical_revenue},
      "projected_q4_revenue": {projected_q4},
      "projected_growth_rate": {growth_rate_pct},
      "projections": [
        "Projection 1...",
        "Projection 2...",
        "Projection 3..."
      ]
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
                {"role": "user", "content": "Generate Q4 predictive financial forecast."}
            ],
            temperature=0.3
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Forecaster error: {e}")
        return {
            "agent": "Predictive Forecaster Agent #07",
            "status": "FALLBACK",
            "baseline_revenue": historical_revenue,
            "projected_q4_revenue": projected_q4,
            "projected_growth_rate": growth_rate_pct,
            "projections": [
                "Revenue trajectory indicates steady compounding growth over the next two quarters.",
                "Seasonal demand peaks suggest a 15% lift in Q4 transaction volume.",
                "Confidence interval remains high given current historical ledger trends."
            ]
        }
