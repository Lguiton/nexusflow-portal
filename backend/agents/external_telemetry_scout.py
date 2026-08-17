import os, json, logging
from typing import Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)
logger = logging.getLogger("nexusflow.external_telemetry_scout")
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

def execute_task(client_id: str = "default_client", query: str = "") -> Dict[str, Any]:
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    system_prompt = f"""
    You are the External Telemetry Scout. Client: {safe_client_id}. 
    Your objective is to design ingestion strategies for live external APIs, webhooks, and third-party data streams.
    You must map complex nested JSON payloads into flat structures suitable for DuckDB insertion.
    
    Design the API polling strategy and database schema mapping for: {query}
    
    Respond STRICTLY in JSON: 
    {{
        "agent": "External Telemetry Scout", 
        "status": "COMPLETED", 
        "target_endpoint": "...",
        "duckdb_schema_mapping": {{ "column_name": "data_type" }},
        "insights": ["Ingestion strategy details and rate-limit considerations..."]
    }}
    """
    try:
        if not client: raise ValueError("OpenAI missing.")
        res = client.chat.completions.create(
            model="gpt-4o-mini", response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system_prompt}], temperature=0.3
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        logger.error(f"External Telemetry Scout Error: {e}")
        return {"agent": "External Telemetry Scout", "status": "ERROR", "insights": [str(e)]}
