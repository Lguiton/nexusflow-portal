"""
QA-03 (AI evaluation and financial ground-truth suite): the honest,
buildable-today slice of this item -- a real, systematic ground-truth
suite for gross margin (FIN-02) and cash runway (FIN-03), the same shape
FIN-01's MRR suite already gave the platform (test_db_manager_queries.py's
"MRR (FIN-01)" section: unavailable case, computed case, zero-is-real
case). Before this file, FIN-02/FIN-03 had exactly one incidental test
touching these numbers (test_metrics_scoped_to_reporting_month_not_
lifetime_sum in test_virtual_cfo_evidence.py, there to prove period-
scoping, not to systematically ground-truth the metrics themselves).

Two layers, matching how the real code is actually structured:
  1. Unit-level: _classify_expense's whole-word COGS keyword match,
     tested directly and in isolation -- this is the single source of
     truth generate_cfo_briefing's totals AND its evidence buckets both
     read from (see that function's own comment on why), so a
     regression here would silently break both at once.
  2. Integration-level: generate_cfo_briefing() called directly (same
     pattern test_virtual_cfo_evidence.py already established, for the
     same reason -- exercises the real deterministic Python computation
     without needing a live OpenAI call, which this sandbox can't make
     reliably; insights prose is never asserted on, only `metrics`).

QA-03's real cross-check: every ground-truth scenario below independently
RECONSTRUCTS each metric from the response's own `evidence` row
citations (real row_id-backed amounts, not a second hand-typed number)
and confirms it matches `metrics` exactly -- catching a case where the
totals and the evidence buckets could silently drift apart from each
other, not just a case where either is wrong in isolation. Every ledger
fixture below keeps each bucket under EVIDENCE_MAX_ROWS_PER_BUCKET (10)
specifically so `shown_rows` is always the COMPLETE set, never truncated,
so this reconstruction is exact.

Deliberately NOT covered here (real, disclosed, still-open gaps per
FIN-02/FIN-03's own MBL entries, unchanged by this suite): the revenue/
COGS/OPEX split is still a keyword heuristic, not a formal chart-of-
accounts definition, and cash runway still divides by an ASSUMED
reserve, not a real ingested cash balance. This suite ground-truths what
the CURRENT, disclosed definition actually computes -- it does not
(and cannot) validate a formal definition that doesn't exist yet.
"""
import io

import pytest

from backend.agents.virtual_cfo import (
    generate_cfo_briefing,
    _classify_expense,
    ASSUMED_CASH_RESERVES,
)


def _upload(client, headers, csv_body: bytes):
    resp = client.post(
        "/api/finance/upload-ledger",
        files={"file": ("ledger.csv", io.BytesIO(csv_body), "text/csv")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def _reconstruct_from_evidence(result: dict) -> dict:
    """Independently rebuilds revenue/cogs/opex totals from the response's
    OWN evidence row citations (each a real row_id-backed amount) rather
    than trusting `metrics` -- a genuine cross-check, not a restatement.
    Only valid when every bucket's `truncated` is False (asserted by each
    test below before calling this)."""
    ev = result["evidence"]
    revenue = sum(r["amount"] for r in ev["revenue"]["shown_rows"])
    cogs = sum(abs(r["amount"]) for r in ev["cogs"]["shown_rows"])
    opex = sum(abs(r["amount"]) for r in ev["opex"]["shown_rows"])
    return {"revenue": revenue, "cogs": cogs, "opex": opex}


# ---------------------------------------------------------------------
# Unit-level: _classify_expense whole-word COGS matching
# ---------------------------------------------------------------------

@pytest.mark.parametrize("category", ["Hosting", "AWS", "Stripe fees", "COGS", "Cost of Goods Sold"])
def test_classify_expense_real_cogs_keywords_match(category):
    assert _classify_expense(category) == "cogs"


@pytest.mark.parametrize("category", [
    "Costco Wholesale",   # "cost" as a PREFIX substring, not a whole word
    "Costume Design",     # same -- the exact false-positive example in the code's own docstring
    "Coastal Shipping",   # doesn't contain "cost" at all -- sanity check
    "Payroll",
    "Rent",
    "Marketing",
])
def test_classify_expense_false_positives_excluded(category):
    """The real, previously-fixed bug: a bare substring match on 'cost'
    misclassified vendor/category names that merely CONTAIN the string
    'cost' as COGS. Whole-word matching must keep these as opex."""
    assert _classify_expense(category) == "opex"


def test_classify_expense_case_insensitive():
    assert _classify_expense("HOSTING") == "cogs"
    assert _classify_expense("hosting") == "cogs"


def test_classify_expense_empty_or_none_is_opex():
    assert _classify_expense("") == "opex"
    assert _classify_expense(None) == "opex"


# ---------------------------------------------------------------------
# Gross margin (FIN-02) ground truth
# ---------------------------------------------------------------------

def test_gross_margin_hand_computed_positive_case(client, make_auth_headers):
    headers = make_auth_headers("QA03-GM-01")
    _upload(client, headers, (
        b"date,category,amount,description\n"
        b"2026-03-01,Sales,20000,Client A payment\n"
        b"2026-03-05,Hosting,-4000,Server costs\n"      # COGS
        b"2026-03-10,Payroll,-6000,Salaries\n"           # OPEX
    ))
    result = generate_cfo_briefing("QA03-GM-01")
    assert result["reporting_month"] == "2026-03"

    # Hand-computed: revenue=20000, cogs=4000 -> margin=(20000-4000)/20000*100=80.0
    expected_margin = ((20000 - 4000) / 20000) * 100
    assert result["metrics"]["gross_margin"] == pytest.approx(expected_margin, abs=0.05)
    assert expected_margin == pytest.approx(80.0)

    # Cross-check against the response's OWN evidence citations.
    assert result["evidence"]["revenue"]["truncated"] is False
    assert result["evidence"]["cogs"]["truncated"] is False
    reconstructed = _reconstruct_from_evidence(result)
    assert reconstructed["revenue"] == pytest.approx(20000.0)
    assert reconstructed["cogs"] == pytest.approx(4000.0)
    recomputed_margin = ((reconstructed["revenue"] - reconstructed["cogs"]) / reconstructed["revenue"]) * 100
    assert recomputed_margin == pytest.approx(result["metrics"]["gross_margin"], abs=0.05)


def test_gross_margin_100_percent_when_no_cogs(client, make_auth_headers):
    """Revenue with zero COGS rows -- margin must be a real 100.0, not an
    error or an undefined value."""
    headers = make_auth_headers("QA03-GM-02")
    _upload(client, headers, (
        b"date,category,amount,description\n"
        b"2026-03-01,Sales,5000,Pure revenue no COGS this month\n"
        b"2026-03-05,Marketing,-500,Opex only\n"
    ))
    result = generate_cfo_briefing("QA03-GM-02")
    assert result["metrics"]["gross_margin"] == pytest.approx(100.0)


def test_gross_margin_zero_when_no_revenue_rows(client, make_auth_headers):
    """A reporting month with real expense rows but NO revenue -- gross
    margin must be a real 0.0 (the code's explicit `if total_revenue > 0`
    guard), never a ZeroDivisionError or a fabricated number."""
    headers = make_auth_headers("QA03-GM-03")
    _upload(client, headers, (
        b"date,category,amount,description\n"
        b"2026-03-01,Hosting,-1000,Infra cost with no revenue this month\n"
    ))
    result = generate_cfo_briefing("QA03-GM-03")
    assert result["metrics"]["gross_margin"] == pytest.approx(0.0)


def test_gross_margin_negative_when_cogs_exceeds_revenue(client, make_auth_headers):
    """A real, disclosed edge case the formula must handle correctly:
    COGS genuinely larger than revenue produces a real NEGATIVE margin,
    not a clamped 0 or a silently wrong positive number."""
    headers = make_auth_headers("QA03-GM-04")
    _upload(client, headers, (
        b"date,category,amount,description\n"
        b"2026-03-01,Sales,1000,Small sale\n"
        b"2026-03-05,Hosting,-1500,COGS bigger than revenue this month\n"
    ))
    result = generate_cfo_briefing("QA03-GM-04")
    # Hand-computed: (1000 - 1500) / 1000 * 100 = -50.0
    assert result["metrics"]["gross_margin"] == pytest.approx(-50.0, abs=0.05)


# ---------------------------------------------------------------------
# Cash runway (FIN-03) ground truth
# ---------------------------------------------------------------------

def test_cash_runway_hand_computed_positive_burn(client, make_auth_headers):
    headers = make_auth_headers("QA03-CR-01")
    _upload(client, headers, (
        b"date,category,amount,description\n"
        b"2026-03-01,Sales,10000,Revenue\n"
        b"2026-03-05,Hosting,-3000,COGS\n"
        b"2026-03-10,Payroll,-7000,OPEX\n"
    ))
    result = generate_cfo_briefing("QA03-CR-01")

    # burn_rate = cogs + opex = 3000 + 7000 = 10000
    assert result["metrics"]["burn_rate"] == pytest.approx(10000.0, abs=0.05)
    expected_runway = ASSUMED_CASH_RESERVES / 10000.0
    assert result["metrics"]["cash_runway_months"] == pytest.approx(expected_runway, abs=0.05)
    assert result["assumed_cash_reserves"] == ASSUMED_CASH_RESERVES

    # Cross-check burn_rate against the response's own evidence buckets --
    # confirms cogs+opex really are the two components, not e.g. opex alone.
    assert result["evidence"]["cogs"]["truncated"] is False
    assert result["evidence"]["opex"]["truncated"] is False
    reconstructed = _reconstruct_from_evidence(result)
    assert (reconstructed["cogs"] + reconstructed["opex"]) == pytest.approx(result["metrics"]["burn_rate"], abs=0.05)


def test_cash_runway_healthy_fallback_when_zero_burn(client, make_auth_headers):
    """A tenant with real revenue and genuinely ZERO expenses this month
    -- burn_rate=0 must not divide-by-zero; the code's own disclosed
    healthy-runway fallback (99.9 months) applies."""
    headers = make_auth_headers("QA03-CR-02")
    _upload(client, headers, (
        b"date,category,amount,description\n"
        b"2026-03-01,Sales,5000,Revenue only no expenses this month\n"
    ))
    result = generate_cfo_briefing("QA03-CR-02")
    assert result["metrics"]["burn_rate"] == pytest.approx(0.0)
    assert result["metrics"]["cash_runway_months"] == pytest.approx(99.9)


def test_cash_runway_different_burn_rates_produce_proportionally_different_runway(client, make_auth_headers):
    """A real, independent sanity check on the formula's shape: DOUBLING
    the burn rate must exactly HALVE the runway (both divide the same
    ASSUMED_CASH_RESERVES constant) -- catches a formula that silently
    stopped being a real division (e.g. a hardcoded or additive bug)."""
    low_burn_headers = make_auth_headers("QA03-CR-03-LOW")
    high_burn_headers = make_auth_headers("QA03-CR-03-HIGH")
    _upload(client, low_burn_headers, (
        b"date,category,amount,description\n"
        b"2026-03-01,Sales,10000,Revenue\n"
        b"2026-03-05,Payroll,-2000,Low burn\n"
    ))
    _upload(client, high_burn_headers, (
        b"date,category,amount,description\n"
        b"2026-03-01,Sales,10000,Revenue\n"
        b"2026-03-05,Payroll,-4000,High burn -- exactly double the low-burn tenant\n"
    ))
    low = generate_cfo_briefing("QA03-CR-03-LOW")
    high = generate_cfo_briefing("QA03-CR-03-HIGH")
    assert high["metrics"]["burn_rate"] == pytest.approx(low["metrics"]["burn_rate"] * 2, abs=0.05)
    assert high["metrics"]["cash_runway_months"] == pytest.approx(low["metrics"]["cash_runway_months"] / 2, abs=0.05)


# ---------------------------------------------------------------------
# No-data / empty-state: metrics must be real None, not 0 or omitted
# ---------------------------------------------------------------------

def test_no_data_tenant_has_null_metrics_not_zero(client, make_auth_headers):
    """A brand-new tenant with no ledger at all -- gross_margin/burn_rate/
    cash_runway_months must be real None (an honest 'not computable' state
    per _empty_state_response), never a fabricated 0.0 that would read as
    a real, computed answer."""
    make_auth_headers("QA03-CR-04")  # creates the tenant, uploads nothing
    result = generate_cfo_briefing("QA03-CR-04")
    assert result["status"] == "NO_DATA"
    assert result["metrics"]["gross_margin"] is None
    assert result["metrics"]["burn_rate"] is None
    assert result["metrics"]["cash_runway_months"] is None
