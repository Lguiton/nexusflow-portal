import logging
from typing import Dict, Any, List

logger = logging.getLogger("Eivanta-FinancialIntelligence")

class VirtualCFOAgent:
    """
    Agent #11: The Virtual CFO
    Strategic capital allocation, cash burn projections, and runway modeling for SMB growth.
    """
    def generate_cfo_briefing(self, monthly_revenue: float, monthly_expenses: float, cash_reserves: float) -> Dict[str, Any]:
        net_profit = monthly_revenue - monthly_expenses
        profit_margin_pct = (net_profit / monthly_revenue * 100) if monthly_revenue > 0 else 0.0
        
        # Calculate monthly burn & runway
        if net_profit < 0:
            monthly_burn = abs(net_profit)
            runway_months = round(cash_reserves / monthly_burn, 1) if monthly_burn > 0 else 0.0
            financial_health = "HIGH_BURN_WARNING"
        else:
            monthly_burn = 0.0
            runway_months = 999.0  # Net positive cash flow
            financial_health = "PROFITABLE_GROWTH"

        # Strategic Capital Recommendations
        recommendations = []
        if profit_margin_pct < 20.0:
            recommendations.append("CFO Strategy: Gross margin is below target (20%). Audit variable labor and vendor costs.")
        else:
            recommendations.append("CFO Strategy: Margins are healthy. Allocate 15% of surplus to growth & R&D.")

        if runway_months < 6.0 and runway_months != 999.0:
            recommendations.append(f"CRITICAL: Cash runway is low ({runway_months} months). Implement immediate freeze on non-essential OPEX.")

        return {
            "financial_health_status": financial_health,
            "metrics": {
                "monthly_revenue": monthly_revenue,
                "monthly_expenses": monthly_expenses,
                "net_profit": net_profit,
                "profit_margin_pct": round(profit_margin_pct, 2),
                "monthly_burn_rate": monthly_burn,
                "runway_months": "INDEFINITE" if runway_months == 999.0 else runway_months
            },
            "strategic_recommendations": recommendations
        }


class ComptrollerAgent:
    """
    Agent #12: The Comptroller
    Audits ledger transactions, flags cost anomalies, and categorizes tax-deductible expenses.
    """
    def audit_expense_ledger(self, transactions: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_audited = len(transactions)
        flagged_transactions = []
        categorized_totals = {}

        for tx in transactions:
            category = tx.get("category", "Uncategorized")
            amount = tx.get("amount", 0.0)
            
            # Aggregate totals by category
            categorized_totals[category] = categorized_totals.get(category, 0.0) + amount

            # Flag unusual transaction spikes (> $1,000 or uncategorized)
            if amount > 1000.0 or category == "Uncategorized":
                flagged_transactions.append({
                    "tx_id": tx.get("id"),
                    "amount": amount,
                    "category": category,
                    "reason": "Large expenditure spike requiring executive sign-off" if amount > 1000.0 else "Missing expense classification"
                })

        return {
            "total_transactions_audited": total_audited,
            "flagged_count": len(flagged_transactions),
            "expense_breakdown_by_category": {k: round(v, 2) for k, v in categorized_totals.items()},
            "flagged_items": flagged_transactions,
            "audit_status": "AUDIT_COMPLETE"
        }


# Global Agent Instances
virtual_cfo = VirtualCFOAgent()
comptroller_agent = ComptrollerAgent()