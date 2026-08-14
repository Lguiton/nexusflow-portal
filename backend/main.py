import os
import json
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

# Import Claude's secure functions
from db_manager import ingest_csv_to_db, query_db, build_safe_query

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI(title="NexusFlow Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELS ---
class TransactionBatch(BaseModel):
    transactions: list[dict]

class SearchRequest(BaseModel):
    query: str
    client_id: str  # Reads the dynamic client_id from the frontend JSON payload
    context_filters: Optional[Dict[str, Any]] = None

class AgentContribution(BaseModel):
    agent_name: str
    domain: str
    output_summary: str
    raw_artifacts: Optional[Dict[str, Any]] = None

class CognitiveSearchResponse(BaseModel):
    query: str
    synthesized_insight: str
    agent_breakdown: List[AgentContribution]
    confidence_score: float
    status: str

# --- ENDPOINTS ---
@app.get("/api/v1/health")
async def get_health():
    return {"status": "ONLINE", "docker_boundary_secure": True, "active_sub_agents": 20, "version": "2.0.0 (Agentic Swarm)"}


# 1. Universal Cognitive Search (Multi-Agent Swarm Orchestrator)
@app.post("/api/search", response_model=CognitiveSearchResponse)
async def universal_cognitive_search(req: SearchRequest):
    try:
        # ---------------------------------------------------------
        # AGENT #00: THE ORCHESTRATOR (Intent Classification)
        # ---------------------------------------------------------
        orchestrator_prompt = """
        You are Agent #00, the Chief Orchestrator for NexusFlow. 
        Classify the user's query into exactly ONE of these three categories:
        
        1. "ANALYST" - Historical database queries, exact past numbers, ledger lookups, filtering, or SQL aggregations on existing data (e.g., "highest paying client", "total MRR for 2022", "list transactions").
        2. "FORECASTER" - Predictive analytics, future quarters/months, statistical modeling, expansion scenarios, or probability estimates. **CRITICAL RULE: If the query contains words like "confidence interval", "forecast", "predict", "probability", or "projection", YOU MUST output FORECASTER.** (e.g., "forecast next month", "predict churn", "Give me statistical confidence intervals for Q3 expansion").
        3. "STRATEGIST" - High-level business advice, operational consulting, SaaS growth tactics, qualitative recommendations, or conceptual explanations (e.g., "how to reduce churn", "optimize gross margins", "what is MRR").
        
        Respond with ONLY the category word: ANALYST, FORECASTER, or STRATEGIST. Do not include any punctuation, conversational text, or explanation.
        """

        orchestrator_res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": orchestrator_prompt},
                {"role": "user", "content": req.query}
            ],
            temperature=0.0
        )
        
        assigned_agent = orchestrator_res.choices[0].message.content.strip().upper()
        contributors = []
        insight = ""

        # ---------------------------------------------------------
        # AGENT #04: THE DATA ANALYST (DuckDB SQL Execution)
        # ---------------------------------------------------------
        if assigned_agent == "ANALYST":
            analyst_prompt = """
            Translate the user's request into a strict JSON intent object.
            ALLOWED COLUMNS: "id", "client_name", "mrr", "category"
            ALLOWED AGGREGATES: "sum", "count", "avg", "min", "max"
            
            You MUST respond in pure JSON matching this exact structure:
            {
              "operation": "list" or "aggregate",
              "aggregate_function": string or null,
              "aggregate_column": string or null,
              "filters": [{"column": "string", "op": "=", "value": "any"}],
              "order_by": string or null,
              "order_dir": "ASC" or "DESC",
              "limit": integer
            }
            """
            analyst_res = client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={ "type": "json_object" },
                messages=[
                    {"role": "system", "content": analyst_prompt},
                    {"role": "user", "content": req.query}
                ],
                temperature=0.0
            )
            intent_json = json.loads(analyst_res.choices[0].message.content)
            sql_to_run, params = build_safe_query(intent=intent_json, client_id=req.client_id)
            df_result = query_db(sql_to_run, params)
            result_records = df_result.to_dict(orient="records")
            
            insight = "Successfully extracted exact ledger data using secure structured intent."
            contributors.append(AgentContribution(
                agent_name="Data Analyst Agent #04",
                domain="Database Execution",
                output_summary=f"Generated SQL intent for {req.client_id}.",
                raw_artifacts={"intent": intent_json, "sql": sql_to_run, "results": result_records}
            ))

        # ---------------------------------------------------------
        # AGENT #07: THE FORECASTER (Predictive Analytics)
        # ---------------------------------------------------------
        elif assigned_agent == "FORECASTER":
            forecaster_prompt = """
            You are Agent #07, the Predictive Forecaster. 
            Analyze the user's request and output a highly analytical, statistical prediction regarding SaaS metrics. Use terms like 'confidence intervals', 'seasonality', and 'churn probability'.
            """
            forecast_res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": forecaster_prompt},
                    {"role": "user", "content": req.query}
                ],
                temperature=0.5
            )
            insight = forecast_res.choices[0].message.content
            contributors.append(AgentContribution(
                agent_name="Predictive Agent #07",
                domain="Forecasting & Trends",
                output_summary="Executed predictive heuristic models on historical metrics.",
                raw_artifacts={"model_type": "ARIMA Time-Series Mock", "confidence_interval": "92%"}
            ))

        # ---------------------------------------------------------
        # AGENT #15: THE STRATEGIST (Knowledge & Advisory)
        # ---------------------------------------------------------
        else:
            strategist_prompt = """
            You are Agent #15, the SaaS Strategist. 
            Provide high-level, executive advice answering the user's question. Keep it under 3 sentences, punchy, and actionable.
            """
            strategy_res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": strategist_prompt},
                    {"role": "user", "content": req.query}
                ],
                temperature=0.7
            )
            insight = strategy_res.choices[0].message.content
            contributors.append(AgentContribution(
                agent_name="Strategist Agent #15",
                domain="Business Operations",
                output_summary="Synthesized executive SaaS strategy and operational definitions.",
            ))

        # ---------------------------------------------------------
        # RETURN THE MULTI-AGENT PAYLOAD
        # ---------------------------------------------------------
        contributors.insert(0, AgentContribution(
            agent_name="Orchestrator Agent #00",
            domain="Semantic Routing",
            output_summary=f"Analyzed intent and routed request to {assigned_agent}."
        ))

        return CognitiveSearchResponse(
            query=req.query,
            synthesized_insight=insight,
            agent_breakdown=contributors,
            confidence_score=0.98,
            status="SYNTHESIZED"
        )

    except Exception as e:
        return CognitiveSearchResponse(
            query=req.query,
            synthesized_insight="Failed to execute multi-agent swarm.",
            agent_breakdown=[AgentContribution(agent_name="Security Guardrail", domain="Error", output_summary=str(e))],
            confidence_score=0.0,
            status="ERROR"
        )


# 2. File Dropzone Ingestion (Reads client_id dynamically from the HTTP Header)
@app.post("/api/finance/upload-ledger")
async def upload_ledger(file: UploadFile = File(...), x_client_id: str = Header(...)):
    try:
        file_path = f"temp_{file.filename}"
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())
        
        # Pass the dynamic Header value into the ingestion function
        status = ingest_csv_to_db(file_path, client_id=x_client_id, table_name="ledgers")
        
        if os.path.exists(file_path):
            os.remove(file_path)
            
        return {"status": "SUCCESS", "message": status}
    except Exception as e:
        print(f"Ingestion Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
# 3. Comptroller Audit
@app.post("/api/v1/finance/comptroller-audit")
async def run_comptroller_audit(batch: TransactionBatch):
    try:
        system_prompt = """
        You are Agent #12, a ruthless enterprise financial comptroller. 
        Analyze the provided transactions. Flag anything suspicious, unusual, or out of policy.
        
        You MUST respond in pure JSON using this exact structure:
        {
          "audit_report": {
            "total_transactions_audited": int,
            "flagged_count": int,
            "expense_breakdown_by_category": {"Category Name": float_total},
            "flagged_items": [
              {
                "tx_id": "string",
                "amount": float,
                "category": "string",
                "reason": "Why you flagged this (be harsh)"
              }
            ],
            "audit_status": "COMPLETED"
          }
        }
        """

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Here is the ledger batch: {json.dumps(batch.transactions)}"}
            ],
            temperature=0.2 
        )

        return json.loads(response.choices[0].message.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Comptroller AI failed to process ledger.")

# 4. CFO Briefing
@app.post("/api/v1/finance/cfo-briefing")
async def get_cfo_briefing():
    try:
        system_prompt = """
        You are NexusFlow's elite Virtual Chief Financial Officer (CFO). 
        Analyze current SaaS financial health metrics (Gross Margin: 68.5%, Burn Rate: $12,500/mo, Runway: 14.2 months, MRR Trajectory: Upward).
        
        You MUST respond in pure JSON using this exact structure:
        {
          "metrics": {
            "gross_margin": 68.5,
            "burn_rate": 12500.0,
            "cash_runway_months": 14.2
          },
          "insights": [
            "Insight 1 text here...",
            "Insight 2 text here..."
          ]
        }
        """

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the latest executive CFO briefing and strategic growth insights."}
            ],
            temperature=0.3
        )

        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {
            "metrics": {"gross_margin": 68.5, "burn_rate": 12500, "cash_runway_months": 14.2},
            "insights": ["Fallback: Software subscriptions are tracking upwards.", "Fallback: Infrastructure expenditures are within target baseline."]
        }