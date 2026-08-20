import os
import json
import logging
import duckdb
from typing import Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

logger = logging.getLogger("nexusflow.report_generator")

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

def generate_stakeholder_report(client_id: str = "default_client") -> Dict[str, Any]:
    """
    Agent #06 (Report Generator). Synthesizes processed analytics into structured 
    stakeholder-facing governance and performance reports.
    """
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    
    total_revenue = 0.0
    total_expenses = 0.0
    record_count = 0

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
                rev_res = conn.execute(
                    "SELECT SUM(amount) FROM ledgers WHERE client_id = ? AND amount > 0", 
                    [safe_client_id]
                ).fetchone()
                total_revenue = float(rev_res[0]) if rev_res and rev_res[0] is not None else 0.0

                exp_res = conn.execute(
                    "SELECT SUM(ABS(amount)) FROM ledgers WHERE client_id = ? AND amount < 0", 
                    [safe_client_id]
                ).fetchone()
                total_expenses = float(exp_res[0]) if exp_res and exp_res[0] is not None else 0.0

                count_res = conn.execute(
                    "SELECT COUNT(*) FROM ledgers WHERE client_id = ?", 
                    [safe_client_id]
                ).fetchone()
                record_count = int(count_res[0]) if count_res and count_res[0] is not None else 0
    except Exception as e:
        logger.error(f"DuckDB query error in Report Generator: {e}")
    finally:
        if conn:
            conn.close()

    net_income = total_revenue - total_expenses

    system_prompt = f"""
    You are Agent #06, NexusFlow's Report Generator.
    Tenant: {safe_client_id}
    Ledger Statistics -> Total Revenue: ${total_revenue:,.2f}, Total Outflows: ${total_expenses:,.2f}, Net Position: ${net_income:,.2f}, Ingested Records: {record_count}.

    Synthesize an executive stakeholder debrief covering financial trajectory, operational efficiency, and risk governance.

    You MUST respond in pure JSON using this exact structure:
    {{
      "agent": "Report Generator Agent #06",
      "status": "GENERATED",
      "summary_metrics": {{
        "total_revenue": {total_revenue},
        "total_expenses": {total_expenses},
        "net_income": {net_income},
        "records_audited": {record_count}
      }},
      "executive_sections": [
        {{ "title": "Revenue Realization", "summary": "Analysis content..." }},
        {{ "title": "Expense Governance", "summary": "Analysis content..." }},
        {{ "title": "Strategic Recommendation", "summary": "Analysis content..." }}
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
                {"role": "user", "content": "Generate executive stakeholder governance report."}
            ],
            temperature=0.2
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Report Generator API error: {e}")
        return {
            "agent": "Report Generator Agent #06",
            "status": "FALLBACK",
            "summary_metrics": {
                "total_revenue": total_revenue,
                "total_expenses": total_expenses,
                "net_income": net_income,
                "records_audited": record_count
            },
            "executive_sections": [
                {
                    "title": "Revenue Realization",
                    "summary": f"Audited ledger reflects ${total_revenue:,.2f} in gross transactional inflows across active reporting periods."
                },
                {
                    "title": "Expense Governance",
                    "summary": f"Cumulative operational and infrastructure outflows total ${total_expenses:,.2f}, maintaining a net position of ${net_income:,.2f}."
                },
                {
                    "title": "Strategic Recommendation",
                    "summary": "Maintain continuous ledger synchronization and preserve active risk controls across all tenant processing lanes."
                }
            ]
        }
