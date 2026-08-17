import os, json, logging
from typing import Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)
logger = logging.getLogger("nexusflow.predictive_forecaster")
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

def execute_task(client_id: str = "default_client", query: str = "") -> Dict[str, Any]:
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    system_prompt = f"""
    You are Agent #07, NexusFlow's Predictive Forecaster.
    Client: {safe_client_id}. Generate a 3-month statistical forecast based on this request: {query}
    Respond in pure JSON: {{"agent": "Predictive Forecaster Agent #07", "status": "COMPLETED", "insights": ["..."]}}
    """
    try:
        if not client: raise ValueError("OpenAI missing.")
        res = client.chat.completions.create(
            model="gpt-4o-mini", response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system_prompt}], temperature=0.4
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        logger.error(f"Predictive Forecaster Error: {e}")
        return {"agent": "Predictive Forecaster Agent #07", "status": "ERROR", "insights": [str(e)]}
