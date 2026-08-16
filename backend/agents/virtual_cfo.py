import os
import json
import logging
from typing import Dict, Any
import pandas as pd
from openai import OpenAI

logger = logging.getLogger("nexusflow.virtual_cfo")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_cfo_briefing() -> Dict[str, Any]:
    """
    Agent #08 (BI Analyst / Virtual CFO) + Agent #10 (Growth & Retention Optimization)
    Analyzes financial metrics and generates executive briefs with growth insights.
    """
    system_prompt = """
    You are NexusFlow's elite Virtual Chief Financial Officer (CFO) and Growth Strategist (Agent #08 & #10). 
    Analyze SaaS financial health metrics (Gross Margin: 68.5%, Burn Rate: $12,500/mo, Runway: 14.2 months, MRR Trajectory: Upward).
    
    You MUST respond in pure JSON using this exact structure:
    {
      "metrics": {
        "gross_margin": 68.5,
        "burn_rate": 12500.0,
        "cash_runway_months": 14.2
      },
      "insights": [
        "Insight 1 text here...",
        "Insight 2 text here...",
        "Expansion recommendation text here..."
      ]
    }
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the latest executive CFO briefing, financial health metrics, and account expansion insights."}
            ],
            temperature=0.3
        )
        
        raw_content = response.choices[0].message.content
        if not raw_content:
            raise ValueError("Empty response from OpenAI.")
            
        return json.loads(raw_content)
    except Exception as e:
        logger.error("Virtual CFO briefing generation failed: %s", str(e))
        return {
            "metrics": {"gross_margin": 68.5, "burn_rate": 12500.0, "cash_runway_months": 14.2},
            "insights": [
                "Fallback: Software subscription revenue is tracking upwards.",
                "Fallback: Infrastructure expenditures are within target baseline thresholds."
            ]
        }
