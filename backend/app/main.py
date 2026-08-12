import os
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

from app.ml_agent import churn_agent
from app.rag_service import rag_engine  # <-- Added RAG Engine Import

load_dotenv()

app = FastAPI(title="NexusFlow API Core")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/v1/healthcheck")
async def healthcheck():
    return {"status": "online", "service": "NexusFlow API Core"}

@app.get("/api/v1/analytics/summary")
async def analytics_summary():
    return {
        "total_mrr": 51000.0,
        "total_one_time": 5000.0,
        "active_clients": 2,
        "arpu": 8500.0,
        "gross_margin_percent": 82.5
    }

@app.post("/api/v1/etl/upload")
async def upload_file(file: UploadFile = File(...)):
    contents = await file.read()
    analysis_results = churn_agent.analyze_csv(contents)
    return {
        "filename": file.filename,
        "agent_analysis": analysis_results
    }

@app.get("/api/v1/analytics/mrr-trend")
async def mrr_trend():
    return [
        {"month": "Jan", "mrr": 18000},
        {"month": "Feb", "mrr": 24000},
        {"month": "Mar", "mrr": 29000},
        {"month": "Apr", "mrr": 35000},
        {"month": "May", "mrr": 42000},
        {"month": "Jun", "mrr": 48000},
        {"month": "Jul", "mrr": 55000}
    ]

@app.get("/api/v1/clients")
async def get_clients():
    return [
        {"client_id": "org_101", "mrr": 15000.00, "status": "active", "signup_date": "2026-08-01"},
        {"client_id": "org_102", "mrr": 8500.00, "status": "active", "signup_date": "2026-08-05"},
        {"client_id": "org_103", "mrr": 12000.00, "status": "active", "signup_date": "2026-08-10"},
        {"client_id": "org_104", "mrr": 4500.00, "status": "churned", "signup_date": "2026-07-15"},
        {"client_id": "org_105", "mrr": 11000.00, "status": "active", "signup_date": "2026-08-11"}
    ]

# --- OPENAI AGENT ENDPOINT ---
API_KEY = os.getenv("OPENAI_API_KEY")
client = None
if API_KEY and not API_KEY.startswith("sk-your-actual-api-key"):
    client = OpenAI(api_key=API_KEY)

class AgentQuery(BaseModel):
    question: str

@app.post("/api/v1/agent/query")
async def query_agent(payload: AgentQuery):
    system_context = """
    You are the NexusFlow Business Intelligence AI. You provide executive insights.
    Current Dashboard Data: Total MRR = $51,000, Active Clients = 2, ARPU = $8,500, Gross Margin = 82.5%.
    Client Orgs: org_101 (Active, $15k MRR), org_102 (Active, $8.5k MRR).
    Keep your answers under 3 sentences, professional, and directly address the user's question using this data.
    """
    
    if client:
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_context},
                    {"role": "user", "content": payload.question}
                ]
            )
            return {"agent_response": response.choices[0].message.content}
        except Exception as e:
            return {"agent_response": f"OpenAI Engine Error: {str(e)}"}
    else:
        question = payload.question.lower()
        if "mrr" in question:
            return {"agent_response": "[Simulated] Based on the telemetry, MRR is currently $51,000."}
        return {"agent_response": "[Simulated] Please add your OPENAI_API_KEY to your backend/.env file to enable live AI analysis!"}


# --- NEW VECTOR DB RAG ENDPOINT ---
class QueryRequest(BaseModel):
    vector: list[float]

@app.post("/api/v1/rag/query")
def query_knowledge_base(payload: QueryRequest):
    results = rag_engine.search_docs(payload.vector)
    return {
        "status": "success",
        "matches": results,
        "agent_insight": "Retrieved contextual standard operating procedures from vector store."
    }





