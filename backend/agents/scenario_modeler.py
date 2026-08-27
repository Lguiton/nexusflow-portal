import logging
from typing import Any, Dict, Optional, Tuple

try:
    from backend.db_manager import get_ledger_chart_context
    from backend.agents.virtual_cfo import ASSUMED_CASH_RESERVES
except ImportError:
    from db_manager import get_ledger_chart_context
    from agents.virtual_cfo import ASSUMED_CASH_RESERVES

logger = logging.getLogger("eivanta.scenario_modeler")

# COMP-03 (Competitive Analysis & Feature Roadmap, 26 Aug 2026): real
# what-if simulator on runway/cashflow.
#
# CORRECTION vs that doc's own claim: it described this agent as "already
# half-built and unwired" -- checked directly before starting this build,
# and that was wrong. The file that existed was a 15-line hardcoded stub
# (run_scenario_modeler) that returned a fixed
# {"models_generated": 3, "confidence_score": 0.92} for every input,
# regardless of query -- the exact same "rubber stamp" pattern already
# identified and retired elsewhere this session (sop_manager, the old
# data_analyst stub). Nothing here was reused from that stub; this is a
# real rebuild, not a wiring-up.
#
# ROSTER STATUS (INDUCTED 27 Aug 2026, founder decision): this is Agent
# #14, the 13th named specialist alongside Orchestrator (#00). The
# platform's official operating model is now 14 agents (Orchestrator +
# 13 specialists), up from the prior 13 (Orchestrator + 12) -- reflected
# in agent_registry.py's EXPECTED_AGENTS, AgentDirectory.tsx's
# TRACKED_ORDER, and the Master Build List / Executive Summary docs.
# Reachable via its own dedicated endpoint
# (POST /api/v1/predictive/scenario) and real UI card
# (ScenarioModelerCard.tsx on the Analytics tab).
SCENARIO_TYPES = ("price_change_pct", "new_hire_monthly_cost", "churned_account_monthly_revenue")


def _baseline_monthly_figures(monthly_revenue_totals, monthly_totals) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Real baseline: the most recently completed real month's revenue and net
    position, both sourced from db_manager.get_ledger_chart_context (the
    same source every other real finance endpoint in this codebase reads
    from -- kpi-summary, analytics-summary, the BI chart suite).

    Deliberately NOT the lifetime-total-as-if-monthly approach
    virtual_cfo.py's burn_rate uses (sum of every row ever ingested, no
    date grouping) -- that simplification is called out and deliberately
    left alone in that file's own comments as an existing, disclosed
    business-logic choice, not something to silently propagate into a new
    feature. A real most-recent-month figure is the more defensible
    baseline for a forward-looking "what happens next month" scenario.
    """
    if not monthly_revenue_totals or not monthly_totals:
        return None, None, None
    latest_revenue = monthly_revenue_totals[-1]["total_amount"]
    latest_net = monthly_totals[-1]["total_amount"]
    latest_expense = round(latest_revenue - latest_net, 2)
    return latest_revenue, latest_expense, latest_net


def _runway(cash_reserves: float, monthly_net: Optional[float]) -> Optional[float]:
    """
    None when there's no net figure to compute from, or when the tenant
    isn't burning cash this month (net >= 0) -- a burn-based "months until
    zero" figure isn't a meaningful number to show when nothing is being
    burned. Only a real negative monthly net produces a runway figure.
    """
    if monthly_net is None or monthly_net >= 0:
        return None
    return round(cash_reserves / abs(monthly_net), 1)


def _scenario_insight(scenario_type: str, amount: float, baseline_net: float, projected_net: float,
                       baseline_runway: Optional[float], projected_runway: Optional[float]) -> str:
    net_delta = round(projected_net - baseline_net, 2)
    direction = "improves" if net_delta > 0 else "worsens" if net_delta < 0 else "leaves unchanged"

    if scenario_type == "price_change_pct":
        lead = f"A {amount:+.1f}% price change"
    elif scenario_type == "new_hire_monthly_cost":
        lead = f"A new hire costing ${abs(amount):,.2f}/month"
    else:
        lead = f"Losing an account worth ${abs(amount):,.2f}/month in revenue"

    sentence = f"{lead} {direction} monthly net position by ${abs(net_delta):,.2f} (from ${baseline_net:,.2f} to ${projected_net:,.2f})."

    if baseline_runway is not None or projected_runway is not None:
        b = f"{baseline_runway:.1f}" if baseline_runway is not None else "not burn-limited"
        p = f"{projected_runway:.1f}" if projected_runway is not None else "not burn-limited"
        sentence += f" Cash runway moves from {b} to {p} months under the assumed cash reserve."
    return sentence


async def run_scenario(
    client_id: str,
    scenario_type: str,
    amount: float,
    cash_reserves: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Real deterministic what-if simulator -- no LLM call, same "pure
    arithmetic" posture as /api/v1/finance/kpi-summary and
    /api/v1/finance/analytics-summary. Applies one named scenario to this
    tenant's real most-recent-month revenue/expense baseline and reports
    the resulting monthly net and cash-runway impact, both before and
    after.
    """
    if scenario_type not in SCENARIO_TYPES:
        return {
            "agent": "Scenario Modeler",
            "status": "ERROR",
            "insights": [f"Unknown scenario_type '{scenario_type}'. Must be one of: {', '.join(SCENARIO_TYPES)}."],
        }

    reserves = cash_reserves if cash_reserves is not None else ASSUMED_CASH_RESERVES

    context = await get_ledger_chart_context(client_id)
    monthly_revenue_totals = context.get("monthly_revenue_totals", [])
    monthly_totals = context.get("monthly_totals", [])

    baseline_revenue, baseline_expense, baseline_net = _baseline_monthly_figures(monthly_revenue_totals, monthly_totals)

    if baseline_revenue is None:
        return {
            "agent": "Scenario Modeler",
            "status": "NO_DATA",
            "insights": ["No ledger data has been ingested yet for this tenant -- upload a CSV ledger before running a what-if scenario."],
        }

    if scenario_type == "price_change_pct":
        projected_revenue = round(baseline_revenue * (1 + amount / 100.0), 2)
        projected_expense = baseline_expense
    elif scenario_type == "new_hire_monthly_cost":
        projected_revenue = baseline_revenue
        projected_expense = round(baseline_expense + abs(amount), 2)
    else:  # churned_account_monthly_revenue
        projected_revenue = round(baseline_revenue - abs(amount), 2)
        projected_expense = baseline_expense

    projected_net = round(projected_revenue - projected_expense, 2)

    baseline_runway = _runway(reserves, baseline_net)
    projected_runway = _runway(reserves, projected_net)
    runway_delta = round(projected_runway - baseline_runway, 1) if (baseline_runway is not None and projected_runway is not None) else None

    return {
        "agent": "Scenario Modeler",
        "status": "COMPLETED",
        "scenario_type": scenario_type,
        "amount": amount,
        "assumed_cash_reserves": reserves,
        "baseline": {
            "monthly_revenue": baseline_revenue,
            "monthly_expense": baseline_expense,
            "monthly_net": baseline_net,
            "cash_runway_months": baseline_runway,
        },
        "projected": {
            "monthly_revenue": projected_revenue,
            "monthly_expense": projected_expense,
            "monthly_net": projected_net,
            "cash_runway_months": projected_runway,
        },
        "runway_delta_months": runway_delta,
        "insights": [
            _scenario_insight(scenario_type, amount, baseline_net, projected_net, baseline_runway, projected_runway),
            "Cash runway here uses the same assumed cash-reserve figure as Virtual CFO (see the Assumption Ledger) -- not a real bank balance, since Eivanta doesn't ingest one yet. Pass cash_reserves to override it for this one calculation.",
        ],
    }
