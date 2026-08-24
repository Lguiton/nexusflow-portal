from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import logging

try:
    from .db_manager import get_total_ingested_rows, get_advanced_telemetry, init_telemetry_schema, get_ai_usage_summary
except ImportError:
    from db_manager import get_total_ingested_rows, get_advanced_telemetry, init_telemetry_schema, get_ai_usage_summary

try:
    from .agent_registry import agent_registry
except ImportError:
    from agent_registry import agent_registry

try:
    from .auth import verify_jwt_and_get_client_id
except ImportError:
    from auth import verify_jwt_and_get_client_id

router = APIRouter()
logger = logging.getLogger("nexusflow.metrics")


@router.on_event("startup")
async def _startup_init_telemetry():
    # Moved out of a module-level `asyncio.create_task(...)`, which ran at
    # IMPORT time -- before uvicorn's event loop exists -- and would raise
    # "RuntimeError: no running event loop" on startup, likely crashing this
    # router (and possibly the whole app, since main.py's try/except around
    # loading this router only catches ImportError, not RuntimeError).
    # Startup events run inside the real event loop, after it's live.
    await init_telemetry_schema()


class IngestionMetrics(BaseModel):
    total_rows: int
    status: str

class SwarmMetrics(BaseModel):
    registered_agents: int
    total_capacity: int
    task_success_rate: float
    avg_execution_time_sec: float
    agent_status_map: dict
    agent_failures: dict
    integrity_verification: dict
    telemetry_window_stats: dict


@router.get("/api/v1/metrics/ingestion", response_model=IngestionMetrics)
async def get_ingestion_metrics(client_id: str = Depends(verify_jwt_and_get_client_id)):
    # NOTE: get_total_ingested_rows() returns a platform-wide total across
    # ALL tenants -- it isn't filtered to `client_id`'s data in db_manager.py.
    # Requiring a valid token at least closes the "fully public,
    # unauthenticated" gap, but whether this should become a per-tenant
    # count or stay an admin/ops-only metric (gated once real RBAC exists)
    # is a product decision, not something to guess at here.
    try:
        total_rows = await get_total_ingested_rows()
        return {"total_rows": total_rows, "status": "success"}
    except Exception as e:
        logger.error(f"Error fetching ingestion metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch metrics")


@router.get("/api/v1/metrics/swarm", response_model=SwarmMetrics)
async def get_swarm_metrics(client_id: str = Depends(verify_jwt_and_get_client_id)):
    # Same open question as above -- this reports platform-wide swarm/agent
    # health, not anything scoped to `client_id`.
    try:
        active_count, total_capacity, status_map, failures = agent_registry.get_health_status()
        verification_struct = agent_registry.verify_mathematical_integrity()

        # Connect the unified advanced telemetry pipeline
        telemetry_stats = await get_advanced_telemetry(window=100)

        if failures:
            logger.warning(f"Degraded Swarm Roster Detected. Failures: {failures}")

        return {
            "registered_agents": active_count,
            "total_capacity": total_capacity,
            "task_success_rate": telemetry_stats["success_rate_pct"],
            "avg_execution_time_sec": telemetry_stats["avg_execution_time_sec"],
            "agent_status_map": status_map,
            # FIXED (ARCH-03 diagnosis gap): the actual import-failure reason
            # for a DEGRADED agent was only ever logged server-side
            # (logger.warning above) -- never returned in the API response
            # itself, so the "7/8 Active" dashboard state carried no way to
            # find out WHICH agent failed or WHY without reading server
            # console output directly. Now surfaced in the response so the
            # dashboard (and whoever's debugging it) can see the real
            # exception message per failed agent.
            "agent_failures": failures,
            "integrity_verification": verification_struct,
            "telemetry_window_stats": telemetry_stats
        }
    except Exception as e:
        logger.error(f"Failed to fetch swarm metrics from registry: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch swarm telemetry")


@router.get("/api/v1/metrics/ai-usage")
async def get_ai_usage_metrics(client_id: str = Depends(verify_jwt_and_get_client_id)):
    # AI-06: token/cost telemetry. Same disclosed posture as the two metrics
    # endpoints above -- platform-wide aggregate, not scoped to `client_id`,
    # pending a real RBAC/admin tier to gate a per-tenant cost breakdown
    # behind. Every authenticated tenant can currently see this platform-wide
    # total, same as swarm/ingestion metrics already do.
    try:
        return await get_ai_usage_summary(window=500)
    except Exception as e:
        logger.error(f"Failed to fetch AI usage metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch AI usage telemetry")
