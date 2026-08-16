import os
import json
import logging
import pandas as pd
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from openai import OpenAI

# BUG A FIXED: Mathematically resolve the exact path to backend/.env
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

try:
    from backend.db_manager import query_db
except ImportError:
    query_db = None

logger = logging.getLogger("nexusflow.virtual_cfo")

# The client will now successfully load the key
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

def generate_cfo_briefing(client_id: str = "default_client") -> Dict[str, Any]:
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")

    total_revenue = 0.0
    total_expenses = 0.0
    
    if query_db:
        try:
            rev_query = f"SELECT SUM(mrr) as total FROM ledgers WHERE client_id = '{safe_client_id}' AND mrr > 0"
            exp_query = f"SELECT SUM(mrr) as total FROM ledgers WHERE client_id = '{safe_client_id}' AND mrr < 0"
            
            rev_df = query_db(rev_query)
            exp_df = query_db(exp_query)
            
            rev_result = rev_df.to_dict(orient="records") if not rev_df.empty else []
            exp_result = exp_df.to_dict(orient="records") if not exp_df.empty else []
            
            if rev_result and pd.notna(rev_result[0].get('total')):
                total_revenue = float(rev_result[0]['total'])
            if exp_result and pd.notna(exp_result[0].get('total')):
                total_expenses = abs(float(exp_result[0]['total']))
        except Exception as e:
            logger.error(f"Failed to query live ledger data for {safe_client_id}: {e}")

    gross_margin = 0.0
    if total_revenue > 0:
        gross_margin = ((total_revenue - total_expenses) / total_revenue) * 100

    burn_rate = total_expenses
    assumed_cash_reserves = 250000.0
    cash_runway_months = (assumed_cash_reserves / burn_rate) if burn_rate > 0 else 99.9

    data_context = "The ledger is currently empty. Inform the user to upload their CSV financial data."
    if total_revenue > 0 or total_expenses > 0:
        data_context = f"Live Ledger Snapshot -> Revenue: ${total_revenue:,.2f}, Expenses: ${total_expenses:,.2f}."

    system_prompt = f"""
    You are NexusFlow's elite Virtual Chief Financial Officer (CFO). 
    You are analyzing LIVE, cryptographically secured financial data for tenant: {safe_client_id}.
    
    Current Financial Health Metrics:
    - {data_context}
    - Gross Margin: {gross_margin:.1f}%
    - Monthly Burn Rate: ${burn_rate:,.2f}
    - Estimated Cash Runway: {cash_runway_months:.1f} months
    
    Your task is to generate EXACTLY 3 strategic executive insights based ON THIS SPECIFIC DATA. 

    You MUST respond in pure JSON using this exact structure:
    {{
      "metrics": {{
        "gross_margin": {gross_margin:.1f},
        "burn_rate": {burn_rate:.1f},
        "cash_runway_months": {cash_runway_months:.1f}
      }},
      "insights": [
        "Insight 1...",
        "Insight 2...",
        "Insight 3..."
      ]
    }}
    """

    try:
        if not client:
            raise ValueError("OpenAI client not initialized (missing API key). Check backend/.env pathing.")
            
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the executive CFO briefing."}
            ],
            temperature=0.3
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"metrics": {"gross_margin": gross_margin, "burn_rate": burn_rate, "cash_runway_months": cash_runway_months}, "insights": [f"Error: {str(e)}"]}
