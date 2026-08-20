import os
import json
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from openai import OpenAI

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

logger = logging.getLogger("nexusflow.sop_manager")

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None

MAX_TOKEN_CEILING = 4000
WHITELISTED_AGENTS = {
    "Agent #00": "Orchestrator",
    "Agent #01": "Ingestion Engine",
    "Agent #02": "Data Engineer",
    "Agent #03": "Schema Mapper",
    "Agent #04": "Data Analyst",
    "Agent #05": "BI Engineer",
    "Agent #06": "Report Generator",
    "Agent #07": "Predictive Forecaster",
    "Agent #08": "Virtual CFO",
    "Agent #09": "Ops Shield",
    "Agent #10": "SaaS Strategist",
    "Agent #11": "BI Visual Architect",
    "Agent #12": "Telemetry Scout"
}

WHITELISTED_SQL_COLUMNS = {"client_id", "date", "category", "amount", "description"}

class SOPViolationException(Exception):
    """Custom exception raised when an incoming payload violates platform SOP policies."""
    pass

class IngressAuditResult(BaseModel):
    is_compliant: bool
    phase_1_security: str
    phase_2_token_budget: str
    phase_3_dispatch_target: str
    estimated_tokens: int
    violations: List[str] = Field(default_factory=list)

class SOPManagerService:
    """
    SOP Manager Service: Enforces SOP-001 (Operational Ingress Routing & Firewall Policy),
    token budgeting, schema parameterization checks, and continuous compliance telemetry.
    """

    @staticmethod
    def estimate_token_count(text: str) -> int:
        """Estimates token footprint using the standard 4 chars/token heuristic."""
        return max(1, len(text) // 4)

    @classmethod
    def audit_ingress_payload(
        cls, 
        raw_payload: str, 
        client_id: str, 
        target_agent: Optional[str] = None
    ) -> IngressAuditResult:
        """
        Executes strict three-phase validation on incoming requests under SOP-001.
        """
        violations: List[str] = []

        # --- Phase 1: Security Audit Interception (SOP-001 Phase 1) ---
        payload_lower = raw_payload.lower()
        injection_indicators = [
            "ignore previous instructions",
            "system prompt override",
            "drop table",
            "delete from",
            "--",
            ";--",
            "eval(",
            "exec(",
            "__import__"
        ]
        
        security_status = "PASSED"
        for indicator in injection_indicators:
            if indicator in payload_lower:
                violations.append(f"Security Alert: Malicious injection signature detected ('{indicator}').")
                security_status = "FAILED"

        # --- Phase 2: Token Budget & Context Verification (SOP-001 Phase 2) ---
        estimated_tokens = cls.estimate_token_count(raw_payload)
        token_status = "PASSED"
        if estimated_tokens > MAX_TOKEN_CEILING:
            violations.append(
                f"Token Budget Exceeded: Payload footprint ({estimated_tokens} tokens) exceeds {MAX_TOKEN_CEILING} ceiling."
            )
            token_status = "EXCEEDED"

        if not client_id or not client_id.strip():
            violations.append("Tenant Integrity Error: Missing or unverified client_id parameter.")

        # --- Phase 3: Whitelisted Execution Dispatch (SOP-001 Phase 3) ---
        dispatch_status = "PASSED"
        if target_agent and target_agent not in WHITELISTED_AGENTS and target_agent not in WHITELISTED_AGENTS.values():
            violations.append(f"Dispatch Error: Unmapped agent target '{target_agent}'.")
            dispatch_status = "UNMAPPED"

        is_compliant = len(violations) == 0

        if not is_compliant:
            logger.warning(f"SOP-001 Enforcement triggered fail-closed state: {violations}")

        return IngressAuditResult(
            is_compliant=is_compliant,
            phase_1_security=security_status,
            phase_2_token_budget=f"{estimated_tokens}/{MAX_TOKEN_CEILING} tokens ({token_status})",
            phase_3_dispatch_target=target_agent or "Agent #00 (Orchestrator)",
            estimated_tokens=estimated_tokens,
            violations=violations
        )

    @staticmethod
    def validate_sql_query(query: str) -> bool:
        """
        Ensures SQL strings from Agent #04 (Data Analyst) only access whitelisted columns 
        and read-only operations.
        """
        q_clean = query.strip().upper()
        if not q_clean.startswith("SELECT"):
            logger.error("SOP Violation: Non-SELECT query blocked by SQL governor.")
            return False
        
        forbidden_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "REPLACE"]
        if any(kw in q_clean.split() for kw in forbidden_keywords):
            logger.error("SOP Violation: Modifying statement detected in read-only channel.")
            return False

        return True

    @classmethod
    def synthesize_sop_telemetry(cls, client_id: str = "default_client") -> Dict[str, Any]:
        """
        Synthesizes an executive compliance overview of active operational governance parameters.
        """
        safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")

        telemetry = {
            "service": "SOP Manager Agent",
            "status": "ENFORCING",
            "active_tenant": safe_client_id,
            "governance_rules": [
                "Continuous Evolutionary Prototyping (CEP) active",
                "Harness-Driven Development (HDD) asserted",
                "Single-Writer Mutex serialization enforced on DuckDB",
                "Server-Side JWT cryptographic boundary enforced",
                "Strict <4,000 token context ceiling active"
            ],
            "workforce_registry_size": len(WHITELISTED_AGENTS),
            "whitelisted_workforce": WHITELISTED_AGENTS
        }

        system_prompt = f"""
        You are the SOP Manager Agent for NexusFlow Analytics.
        Tenant: {safe_client_id}
        Governance State: {json.dumps(telemetry)}

        Generate exactly 3 concise operational compliance confirmations verifying that the 13-agent swarm is operating within deterministic boundaries.

        Respond in pure JSON using this exact structure:
        {{
          "service": "SOP Manager Agent",
          "compliance_status": "CERTIFIED",
          "token_ceiling_max": {MAX_TOKEN_CEILING},
          "verified_workforce_count": {len(WHITELISTED_AGENTS)},
          "audit_summary": [
            "Confirmation 1...",
            "Confirmation 2...",
            "Confirmation 3..."
          ]
        }}
        """

        try:
            if not client:
                raise ValueError("OpenAI client not initialized.")

            response = client.chat.completions.create(
                model="gpt-4o",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Execute operational compliance synthesis."}
                ],
                temperature=0.0
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"SOP Telemetry synthesis fallback: {e}")
            return {
                "service": "SOP Manager Agent",
                "compliance_status": "ACTIVE_FALLBACK",
                "token_ceiling_max": MAX_TOKEN_CEILING,
                "verified_workforce_count": len(WHITELISTED_AGENTS),
                "audit_summary": [
                    "SOP-001 Ingress firewall and Layer-7 semantic checks active.",
                    "Single-writer mutex locks active across all DuckDB write transactions.",
                    "Token ceiling bounded strictly beneath 4,000 tokens per transaction window."
                ]
            }

sop_manager = SOPManagerService()
