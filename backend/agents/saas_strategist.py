import os
import json
import logging
from typing import Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

logger = logging.getLogger("nexusflow.saas_strategist")

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

def generate_strategy(client_id: str = "default_client") -> Dict[str, Any]:
    """
    Agent #10 (SaaS Strategist). Provides high-level business strategy and operational optimization.
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")

    system_prompt = f"""
    You are Agent #10, NexusFlow's SaaS Strategist and Business Advisor.
    Tenant: {safe_client_id}
    
    Provide exactly 3 enterprise-grade SaaS growth and operational optimization strategies.
    
    You MUST respond in pure JSON using this exact structure:
    {{
      "agent": "SaaS Strategist Agent #10",
      "status": "OPTIMIZED",
      "strategies": [
        "Strategy 1...",
        "Strategy 2...",
        "Strategy 3..."
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
                {"role": "user", "content": "Generate strategic SaaS growth advisory."}
            ],
            temperature=0.3
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"SaaS Strategist error: {e}")
        return {
            "agent": "SaaS Strategist Agent #10",
            "status": "FALLBACK",
            "strategies": [
                "Optimize customer acquisition cost (CAC) through automated referral loops.",
                "Enhance tiered pricing models to capture higher expansion revenue.",
                "Streamline infrastructure resource allocation to maximize net margins."
            ]
        }
