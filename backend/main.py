import os
import re
import json
import logging
import asyncio
import glob
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

from backend.db_manager import ingest_csv_to_db

def get_active_agent_count() -> int:
    try:
        agents_dir = os.path.join(os.path.dirname(__file__), 'agents')
        agent_files = glob.glob(os.path.join(agents_dir, '*.py'))
        return len([f for f in agent_files if not f.endswith('__init__.py')])
    except Exception:
        return 0

def sanitize_client_id(client_id: str) -> str:
    """Strip anything that isn't alphanumeric, underscore, or hyphen to prevent
    path traversal / injection if client_id is ever used in file paths or logs."""
    return re.sub(r'[^A-Za-z0-9_-]', '', client_id or "")[:128] or "default_client"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("nexusflow.supervisor")

app = FastAPI(title="NexusFlow Backend - Hardened Enterprise Edition")

try:
    from backend.routers import swarm
    app.include_router(swarm.router)
except ImportError as e:
    logger.error(f"Failed to load swarm router: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8001", "http://127.0.0.1:8001"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# NOTE: 'unsafe-inline' below is a known, flagged gap (see Section 1 of the
# Project Audit) — it weakens what CSP protects against. Tightening it
# requires touching the frontend's inline script/style usage, which is out
# of scope for this pass since it would mean editing frontend files too.
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';"
    return response

class SearchRequest(BaseModel):
    query: str
    client_id: Optional[str] = "default_client"

@app.get("/api/v1/health")
async def get_health():
    active_agents = get_active_agent_count()
    return {
        "status": "SECURE_ONLINE",
        "docker_boundary_secure": True,
        "concurrency_lock": "ACTIVE",
        "active_sub_agents": active_agents,
        "version": "2.2.1 (Hardened Production Architecture)"
    }

@app.post("/api/finance/upload-ledger")
async def upload_ledger(file: UploadFile = File(...), x_client_id: str = Header(default="default_client", alias="x-client-id")):
    client_id = sanitize_client_id(x_client_id)
    # Use only the base filename (Path(...).name) to prevent a filename like
    # "../../etc/something" from writing outside the intended temp directory.
    safe_filename = Path(file.filename or "upload.csv").name
    temp_dir = Path("/tmp/nexusflow_ingest")
    temp_dir.mkdir(parents=True, exist_ok=True)
    file_path = temp_dir / f"{client_id}_{safe_filename}"
    try:
        with open(file_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                buffer.write(chunk)
        result_msg = await asyncio.to_thread(ingest_csv_to_db, str(file_path), client_id)
        return {"status": "SUCCESS", "message": result_msg}
    except Exception as e:
        logger.error(f"Ledger upload error: {e}")
        raise HTTPException(status_code=500, detail="Ledger ingestion failed. Check server logs for details.")
    finally:
        if file_path.exists():
            file_path.unlink()

@app.post("/api/search")
async def secure_cognitive_search(req: SearchRequest, x_client_id: str = Header(default="default_client", alias="x-client-id")):
    client_id = sanitize_client_id(req.client_id or x_client_id)
    try:
        from backend.agents.orchestrator import route_query
        result = await asyncio.to_thread(route_query, req.query, client_id)
        return result
    except Exception as e:
        # FIX: previously this returned a fabricated, plausible-looking
        # success payload ("confidence": 0.85, a fake routed_to target) on
        # a real internal error. That silently hands the user a fake answer
        # instead of a real error state. Now it raises instead.
        logger.error(f"Cognitive search routing error: {e}")
        raise HTTPException(status_code=502, detail="Search routing failed. Please try again.")

@app.post("/api/v1/finance/cfo-briefing")
async def get_cfo_briefing(x_client_id: str = Header(default="default_client", alias="x-client-id")):
    client_id = sanitize_client_id(x_client_id)
    try:
        from backend.agents.virtual_cfo import generate_cfo_briefing
        result = await asyncio.to_thread(generate_cfo_briefing, client_id)
        return result
    except Exception as e:
        # FIX: previously returned hardcoded fake financials
        # (gross_margin: 72.0, burn_rate: 150000.0, ...) on failure, which
        # is indistinguishable from a real briefing to the frontend/user.
        # Fabricated financial figures on error is a trust-critical bug.
        logger.error(f"CFO Briefing Error: {e}")
        raise HTTPException(status_code=502, detail="CFO briefing generation failed. Please try again.")

@app.post("/api/v1/data/schema-audit")
async def run_schema_audit(x_client_id: str = Header(default="default_client", alias="x-client-id")):
    client_id = sanitize_client_id(x_client_id)
    try:
        from backend.agents.data_engineer import analyze_schema_quality
        result = await asyncio.to_thread(analyze_schema_quality, client_id)
        return result
    except Exception as e:
        logger.error(f"Data Engineer Audit Error: {e}")
        raise HTTPException(status_code=502, detail="Schema audit failed. Please try again.")

@app.post("/api/v1/bi/summary")
async def get_bi_summary(x_client_id: str = Header(default="default_client", alias="x-client-id")):
    client_id = sanitize_client_id(x_client_id)
    try:
        from backend.agents.bi_engineer import generate_bi_summary
        result = await asyncio.to_thread(generate_bi_summary, client_id)
        return result
    except Exception as e:
        logger.error(f"BI Summary Error: {e}")
        raise HTTPException(status_code=502, detail="BI summary generation failed. Please try again.")

@app.post("/api/v1/predictive/forecast")
async def get_forecast(x_client_id: str = Header(default="default_client", alias="x-client-id")):
    client_id = sanitize_client_id(x_client_id)
    try:
        from backend.agents.predictive_forecaster import generate_forecast
        result = await asyncio.to_thread(generate_forecast, client_id)
        return result
    except Exception as e:
        logger.error(f"Forecaster Error: {e}")
        raise HTTPException(status_code=502, detail="Forecast generation failed. Please try again.")

@app.post("/api/v1/saas/strategy")
async def get_saas_strategy(x_client_id: str = Header(default="default_client", alias="x-client-id")):
    client_id = sanitize_client_id(x_client_id)
    try:
        from backend.agents.saas_strategist import generate_strategy
        result = await asyncio.to_thread(generate_strategy, client_id)
        return result
    except Exception as e:
        logger.error(f"SaaS Strategist Error: {e}")
        raise HTTPException(status_code=502, detail="Strategy generation failed. Please try again.")

@app.post("/api/v1/reports/stakeholder")
async def get_stakeholder_report(x_client_id: str = Header(default="default_client", alias="x-client-id")):
    client_id = sanitize_client_id(x_client_id)
    try:
        from backend.agents.report_generator import generate_stakeholder_report
        result = await asyncio.to_thread(generate_stakeholder_report, client_id)
        return result
    except Exception as e:
        logger.error(f"Report Generator Error: {e}")
        raise HTTPException(status_code=502, detail="Stakeholder report generation failed. Please try again.")

@app.post("/api/v1/governance/sop-audit")
async def get_sop_compliance_audit(x_client_id: str = Header(default="default_client", alias="x-client-id")):
    client_id = sanitize_client_id(x_client_id)
    try:
        from backend.agents.sop_manager import generate_sop_compliance_audit
        result = await asyncio.to_thread(generate_sop_compliance_audit, client_id)
        return result
    except Exception as e:
        logger.error(f"SOP Governance Audit Error: {e}")
        raise HTTPException(status_code=502, detail="SOP governance audit failed. Please try again.")