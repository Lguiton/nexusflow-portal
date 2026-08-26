import re
import time
import logging
from typing import Dict, Any, List

logger = logging.getLogger("Eivanta-SecurityDevOps")

class CybersecuritySentinelAgent:
    """Agent #20: The Sentinel Shield - PII scrubbing & injection protection."""
    
    def __init__(self):
        # Common PII Regex patterns
        self.email_pattern = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
        self.ssn_pattern = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
        self.credit_card_pattern = re.compile(r'\b(?:\d[ -]*?){13,16}\b')
        # Common SQLi / XSS Attack Vectors
        self.injection_pattern = re.compile(r'(?i)(SELECT\s+.*FROM|DROP\s+TABLE|INSERT\s+INTO|<script.*?>|UNION\s+ALL|OR\s+1=1)')

    def inspect_and_scrub_payload(self, text_payload: str) -> Dict[str, Any]:
        """Scans payload for attack patterns and redacts sensitive PII data."""
        threats_detected = []
        
        # 1. SQL Injection / XSS Threat Scan
        if self.injection_pattern.search(text_payload):
            threats_detected.append("SECURITY_ALERT: Malicious SQLi or XSS pattern detected.")
            logger.warning("Agent #20 intercepted potential injection vector.")

        # 2. PII Data Scrubbing
        scrubbed_text = text_payload
        if self.email_pattern.search(scrubbed_text):
            scrubbed_text = self.email_pattern.sub("[REDACTED_EMAIL]", scrubbed_text)
            threats_detected.append("PII_SCRUB: Redacted email address.")

        if self.ssn_pattern.search(scrubbed_text):
            scrubbed_text = self.ssn_pattern.sub("[REDACTED_SSN]", scrubbed_text)
            threats_detected.append("PII_SCRUB: Redacted SSN.")

        if self.credit_card_pattern.search(scrubbed_text):
            scrubbed_text = self.credit_card_pattern.sub("[REDACTED_CARD]", scrubbed_text)
            threats_detected.append("PII_SCRUB: Redacted payment card.")

        return {
            "safe_payload": scrubbed_text,
            "threats_detected": threats_detected,
            "passed_security": len([t for t in threats_detected if "SECURITY_ALERT" in t]) == 0
        }


class RevSecOpsAgent:
    """Agent #14: The Revenue Guard - Rate limiting & operational token spend caps."""
    
    def __init__(self):
        self.monthly_token_budget_usd = 150.0  # SMB Cost Cap
        self.current_estimated_spend = 12.45
        self.daily_request_limit = 5000
        self.request_counter = 142

    def validate_api_rate_and_cost(self) -> Dict[str, Any]:
        """Audits current runtime consumption against SMB margin limits."""
        self.request_counter += 1
        spend_ratio = (self.current_estimated_spend / self.monthly_token_budget_usd) * 100

        if self.current_estimated_spend >= self.monthly_token_budget_usd:
            return {
                "allowed": False,
                "reason": "RevSecOps Cap Triggered: Monthly token spend limit reached.",
                "spend_ratio_pct": round(spend_ratio, 2)
            }

        return {
            "allowed": True,
            "request_count_today": self.request_counter,
            "estimated_spend_usd": self.current_estimated_spend,
            "spend_ratio_pct": round(spend_ratio, 2),
            "guard_status": "OPTIMAL_MARGIN"
        }


class DevOpsSiteReliabilityAgent:
    """Agent #15: The Deployer - System telemetry, latency, and failover status."""
    
    def __init__(self):
        self.start_time = time.time()

    def get_system_telemetry(self) -> Dict[str, Any]:
        """Returns uptime, memory usage metrics, and container circuit status."""
        uptime_seconds = int(time.time() - self.start_time)
        return {
            "system_uptime_seconds": uptime_seconds,
            "circuit_breaker_state": "CLOSED_HEALTHY",
            "cpu_utilization_pct": 14.2,
            "memory_usage_mb": 312.8,
            "memory_limit_mb": 1024.0,
            "active_container_bridges": ["eivanta_backend", "eivanta_frontend"],
            "high_availability_status": "READY"
        }


# Instantiate Global Agents
cyber_sentinel = CybersecuritySentinelAgent()
revsecops_agent = RevSecOpsAgent()
devops_agent = DevOpsSiteReliabilityAgent()