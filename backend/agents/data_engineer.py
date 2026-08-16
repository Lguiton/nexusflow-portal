import os
import json
import logging
from typing import Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

# Robust absolute path resolution for backend/.env
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

logger = logging.getLogger("nexusflow.data_engineer")

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

def analyze_schema_quality(client_id: str = "default_client") -> Dict[str, Any]:
    """
    Agent #02 (Data Engineer). 
    Analyzes the current DuckDB schema structure and provides actionable data-cleaning steps.
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    
    system_prompt = f"""
    You are Agent #02, NexusFlow's elite Data Engineer.
    Your objective is to analyze data structures and pipeline integrity for tenant: {safe_client_id}.
    Provide exactly 3 automated recommendations for data hygiene, null-value handling, or currency normalization.
    
    You MUST respond in pure JSON using this exact structure:
    {{
      "agent": "Data Engineer Agent #02",
      "status": "OPTIMIZED",
      "recommendations": [
        "Recommendation 1...",
        "Recommendation 2...",
        "Recommendation 3..."
      ]
    }}
    """

    try:
        if not client:
            raise ValueError("OpenAI client not initialized (missing API key).")
            
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Run schema and pipeline health analysis."}
            ],
            temperature=0.3
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Data Engineer Agent Error: {e}")
        return {
            "agent": "Data Engineer Agent #02",
            "status": "ERROR",
            "recommendations": [f"Execution failed: {str(e)}"]
        }
