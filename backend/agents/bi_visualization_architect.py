import os, json, logging
from typing import Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)
logger = logging.getLogger("nexusflow.bi_visualization_architect")
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

def execute_task(client_id: str = "default_client", query: str = "") -> Dict[str, Any]:
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    system_prompt = f"""
    You are the BI Visualization Architect. Client: {safe_client_id}. 
    Your objective is to translate raw data requests into dynamic frontend chart configurations.
    Focus on best practices for categorical data visualization (e.g., Pareto charts, horizontal/vertical stacked bar charts, pie charts, and numerical frequency distributions).
    
    Design the optimal Recharts JSON structure for the following request: {query}
    
    Respond STRICTLY in JSON: 
    {{
        "agent": "BI Visualization Architect", 
        "status": "COMPLETED", 
        "recommended_chart_type": "...",
        "recharts_config": {{ "xAxis": "...", "dataKeys": ["..."] }},
        "insights": ["Why this chart type is optimal for this data payload..."]
    }}
    """
    try:
        if not client: raise ValueError("OpenAI missing.")
        res = client.chat.completions.create(
            model="gpt-4o-mini", response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system_prompt}], temperature=0.2
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        logger.error(f"BI Visualization Architect Error: {e}")
        return {"agent": "BI Visualization Architect", "status": "ERROR", "insights": [str(e)]}
