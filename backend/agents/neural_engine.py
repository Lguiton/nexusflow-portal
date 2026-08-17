import os, json, logging
from typing import Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)
logger = logging.getLogger("nexusflow.neural_engine")
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

def execute_task(client_id: str = "default_client", query: str = "") -> Dict[str, Any]:
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    system_prompt = f"""
    You are the Neural Engine. Client: {safe_client_id}. 
    Process complex semantic reasoning or pattern recognition for: {query}
    Respond in pure JSON: {{"agent": "Neural Engine", "status": "COMPLETED", "insights": ["..."]}}
    """
    try:
        if not client: raise ValueError("OpenAI missing.")
        res = client.chat.completions.create(
            model="gpt-4o-mini", response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system_prompt}], temperature=0.4
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        logger.error(f"Neural Engine Error: {e}")
        return {"agent": "Neural Engine", "status": "ERROR", "insights": [str(e)]}
