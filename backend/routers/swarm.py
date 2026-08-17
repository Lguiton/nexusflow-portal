import logging
from fastapi import APIRouter
from pydantic import BaseModel

# Import our agents
from backend.agents import (
    bi_visualization_architect,
    external_telemetry_scout,
    predictive_forecaster,
    data_analyst
    # virtual_cfo is handled separately via direct RAG endpoints
)

router = APIRouter()
logger = logging.getLogger("nexusflow.swarm")

class SwarmRequest(BaseModel):
    client_id: str
    query: str

@router.post("/route")
async def route_to_swarm(req: SwarmRequest):
    """
    The Master Supervisor Routing Logic.
    Note: Security (Ops Shield) is handled in main.py middleware before traffic reaches here.
    """
    q = req.query.lower()
    
    # 1. BI Visualization Architect Routing (Agent #11)
    if any(kw in q for kw in ["chart", "graph", "visualize", "plot", "pie", "bar", "pareto", "histogram"]):
        logger.info(f"Routing to BI Visualization Architect for {req.client_id}")
        result = bi_visualization_architect.execute_task(req.client_id, req.query)
        return {"agent": "BI Visualization Architect (Agent #11)", "result": result}
        
    # 2. External Telemetry Scout Routing (Agent #12)
    elif any(kw in q for kw in ["api", "webhook", "stream", "external data", "fetch", "telemetry"]):
        logger.info(f"Routing to External Telemetry Scout for {req.client_id}")
        result = external_telemetry_scout.execute_task(req.client_id, req.query)
        return {"agent": "External Telemetry Scout (Agent #12)", "result": result}
        
    # 3. Predictive Forecaster Routing (Agent #07)
    elif any(kw in q for kw in ["forecast", "predict", "future", "growth", "projection"]):
        logger.info(f"Routing to Predictive Forecaster for {req.client_id}")
        result = predictive_forecaster.execute_task(req.client_id, req.query)
        return {"agent": "Predictive Forecaster (Agent #07)", "result": result}
        
    # 4. Default Fallback: Data Analyst (Agent #04)
    else:
        logger.info(f"Routing to Data Analyst for {req.client_id}")
        result = data_analyst.execute_task(req.client_id, req.query)
        return {"agent": "Data Analyst (Agent #04)", "result": result}
