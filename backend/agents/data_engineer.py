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
    Agent #02 (Systems Analyst & Data Engineer). 
    Analyzes the current DuckDB schema structure and pipeline integrity.
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    
    system_prompt = f"""
    You are Agent #02, NexusFlow's Systems Analyst and Data Engineer.
    Your objective is to analyze data structures, system workflows, and pipeline integrity for tenant: {safe_client_id}.
    Provide exactly 3 automated recommendations for data hygiene, system optimization, or pipeline reliability.
    
    You MUST respond in pure JSON using this exact structure:
    {{
      "agent": "Systems Analyst Agent #02",
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
        logger.error(f"Systems Analyst Agent Error: {e}")
        return {
            "agent": "Systems Analyst Agent #02",
            "status": "ERROR",
            "recommendations": [f"Execution failed: {str(e)}"]
        }

def diagnose_and_propose_fix(client_id: str, error_traceback: str, file_content: str, file_name: str) -> Dict[str, Any]:
    """
    Agent #02 (Systems Analyst & Data Engineer) - HITL Self-Healing Workflow.
    Diagnoses system errors and proposes a code fix. STRICTLY READ-ONLY.
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    
    # SECURITY HARDENING: Truncate inputs to prevent token exhaustion / DoS attacks
    safe_traceback = str(error_traceback)[:2000]
    safe_content = str(file_content)[:5000]
    # SECURITY HARDENING: Sanitize file name to prevent path traversal
    safe_file_name = "".join(c for c in file_name if c.isalnum() or c in "-_./")

    system_prompt = f"""
    You are Agent #02, NexusFlow's Systems Analyst and Data Engineer.
    Tenant Context: {safe_client_id}
    
    Your role is to act as the bridge between business requirements and technical infrastructure.
    You are currently engaged in the Human-in-the-Loop (HITL) Self-Healing Workflow.
    
    SECURITY DIRECTIVE: 
    - You are strictly read-only.
    - You must NEVER apply fixes directly to production.
    - You must draft a precise Git diff or technical specification for human approval.
    
    TASK:
    Analyze the following error traceback and the associated file content for '{safe_file_name}'.
    1. Identify the root cause of the inefficiency or breaking point.
    2. Evaluate the cost-benefit of the proposed technical change.
    3. Provide a safe, optimized code fix (diff format or replacement block).
    
    Error Traceback:
    {safe_traceback}
    
    File Content snippet:
    {safe_content}

    You MUST respond in pure JSON using this exact structure:
    {{
      "agent": "Systems Analyst Agent #02",
      "status": "AWAITING_APPROVAL",
      "diagnosis": "<Clear explanation of the root cause>",
      "cost_benefit_analysis": "<Impact of the fix vs leaving it as is>",
      "affected_file": "{safe_file_name}",
      "proposed_fix": "<Exact code block or diff to resolve the issue>"
    }}
    """

    try:
        if not client:
            raise ValueError("OpenAI client not initialized (missing API key).")
            
        response = client.chat.completions.create(
            model="gpt-4o", 
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Diagnose the error and propose a HITL fix."}
            ],
            temperature=0.1
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Systems Analyst HITL Error: {e}")
        return {
            "agent": "Systems Analyst Agent #02",
            "status": "ERROR",
            "diagnosis": f"Failed to analyze: {str(e)}",
            "cost_benefit_analysis": "N/A",
            "affected_file": safe_file_name,
            "proposed_fix": "N/A"
        }
