import importlib
import logging
from typing import Dict, List, Tuple
 
logger = logging.getLogger("eivanta.registry")
 
# Explicit list of mandatory enterprise agent module paths.
#
# OPEN QUESTION: the project debrief describes a 13-agent roster
# (Orchestrator #00 through External Telemetry Scout #12). 8 are tracked
# here. Schema Mapper (#03) is CONFIRMED not built as a separate module --
# its documented responsibility (DuckDB indexing, tenant isolation at the
# DB layer) is instead covered by db_manager.py directly. Ingestion Engine
# (#01), Data Analyst (#04), BI Visualization Architect (#11), and External
# Telemetry Scout (#12) remain unconfirmed either way. Worth resolving
# deliberately rather than letting "registered_agents" quietly imply a
# headcount that isn't real.
EXPECTED_AGENTS: List[str] = [
    "backend.agents.orchestrator",
    "backend.agents.virtual_cfo",
    "backend.agents.data_engineer",
    "backend.agents.bi_engineer",
    "backend.agents.predictive_forecaster",
    "backend.agents.saas_strategist",
    "backend.agents.report_generator",
    "backend.agents.ops_shield",
    # sop_manager intentionally removed -- retired, not part of the
    # canonical 13-agent roster. Its compliance-audit function always
    # returned "CERTIFIED" regardless of actual system state (including in
    # its own error-fallback path), so it wasn't providing a real check that
    # needed replacing.
]
 
class AgentRegistry:
    def __init__(self):
        self._registry: Dict[str, bool] = {}
        self._failures: Dict[str, str] = {}
        self.initialize_registry()
 
    def initialize_registry(self) -> None:
        """
        Attempts to import each expected agent module and records runtime
        health.
 
        NOTE ON SCOPE: "success" here means the Python module imported
        without raising -- it does NOT confirm the agent's actual functions
        (e.g. route_query, generate_forecast) work correctly, or even that
        they exist with the expected signature. A module that imports
        cleanly but has a broken or missing function inside it would still
        be reported here as active/"HEALTHY". If you want a genuine
        functional check, each agent module would need to expose its own
        lightweight self-test that this registry calls -- that's a design
        decision for the agent modules themselves, not something to invent
        here without seeing them.
        """
        for module_path in EXPECTED_AGENTS:
            agent_name = module_path.split(".")[-1]
            try:
                importlib.import_module(module_path)
                self._registry[agent_name] = True
                logger.info(f"Agent Registry: Successfully verified and loaded '{agent_name}'.")
            except Exception as e:
                self._registry[agent_name] = False
                self._failures[agent_name] = str(e)
                logger.error(f"Agent Registry CRITICAL: Failed to load agent '{agent_name}': {e}")
 
    def get_health_status(self) -> Tuple[int, int, Dict[str, bool], Dict[str, str]]:
        """Returns active count, total expected count, full status map, and failure logs."""
        active_count = sum(1 for status in self._registry.values() if status)
        total_expected = len(EXPECTED_AGENTS)
        return active_count, total_expected, self._registry, self._failures
 
    def verify_mathematical_integrity(self) -> dict:
        """
        Returns structured verification metrics for the agent registration
        loop.
 
        NAMING NOTE: despite the name, this measures MODULE IMPORT success
        (did each agent's .py file load without a Python exception), not
        the correctness of any statistical/forecasting computation those
        agents perform. Kept as-is since metrics.py calls this exact method
        name -- flagging here so "100% integrity" isn't read as "our
        forecasting math was verified," which it doesn't check.
        """
        active, total, statuses, failures = self.get_health_status()
        success_ratio = (active / total) * 100 if total > 0 else 0.0
        return {
            "total_expected": total,
            "active_verified": active,
            "failed_count": len(failures),
            "integrity_success_ratio_pct": round(success_ratio, 2),
            "status": "HEALTHY" if active == total else "DEGRADED"
        }
 
# Singleton instance initialized at application startup
agent_registry = AgentRegistry()
 
 