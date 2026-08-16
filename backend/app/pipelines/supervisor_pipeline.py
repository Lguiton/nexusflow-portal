import logging
from typing import List, Dict, Any

logger = logging.getLogger("nexusflow.pipeline.supervisor_pipeline")

class SupervisorPipelineManager:
    """
    Manages multi-turn execution flows and agent step tracing across the 10-agent network.
    """
    def __init__(self):
        self.active_steps: List[Dict[str, Any]] = []

    def record_step(self, agent_name: str, status: str, payload: Dict[str, Any]) -> dict:
        step = {"agent": agent_name, "status": status, "payload": payload}
        self.active_steps.append(step)
        logger.info("Pipeline Step Recorded [%s]: %s", agent_name, status)
        return step

    def clear_pipeline(self):
        self.active_steps.clear()
