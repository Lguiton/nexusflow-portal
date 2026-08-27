"""
DIFF-09: real coverage for the deterministic `evidence` field
backend/agents/virtual_cfo.py's generate_cfo_briefing() attaches alongside
its existing free-text `insights`.

FIN-02/FIN-03 (27 Aug 2026): generate_cfo_briefing() now scopes every metric
and evidence bucket to the tenant's most recently completed REAL calendar
month (see REPORTING_PERIOD_NOTE / reporting_month in virtual_cfo.py), not a
lifetime sum. Fixtures below are built explicitly around that: CSV_BODY
spans two months (June AND July 2026) specifically so the tests can assert
the older month (June) is excluded from every total and evidence bucket,
not just that the newer month (July) is present.

Deliberately does NOT assert on `insights` content or on which path (live
LLM vs template fallback) produced it -- that's genuinely nondeterministic
in this sandbox (a real network call to OpenAI with a placeholder API key
fails differently depending on what the SDK/service does with a bad key,
and this suite must never depend on a live OpenAI response to pass). What
IS asserted is exactly the part DIFF-09/FIN-02/FIN-03 is about: the
evidence field and the reporting-month scoping are computed in Python from
the real ledger rows, identically regardless of which narrative path ran --
these tests call generate_cfo_briefing() directly (not through the HTTP
endpoint) precisely so they exercise that real, deterministic code path
without needing the endpoint's auth/budget plumbing at all.
"""
import io

import pytest

from backend.agents.virtual_cfo import generate_cfo_briefing, REPORTING_PERIOD_NOTE


def _upload(client, auth_headers, csv_body: bytes):
    resp = client.post(
        "/api/finance/upload-ledger",
        files={"file": ("ledger.csv", io.BytesIO(csv_body), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text


# Two months of data on purpose: June (2026-06) is the OLDER, non-reporting
# month and must be excluded entirely from metrics/evidence once FIN-02/
# FIN-03 scoping is in effect. July (2026-07) is the most recently completed
# month present, so it's the resolved reporting_month. A second July Sales
# row (07-15, later date than 07-01) is included specifically so the
# most-recent-first sort within a bucket is still exercised post-scoping.
CSV_BODY = (
    b"date,category,amount,description\n"
    b"2026-06-01,Sales,10000,June revenue -- OLDER month must be EXCLUDED\n"
    b"2026-06-05,Hosting,-2000,June infra -- OLDER month must be EXCLUDED\n"
    b"2026-07-01,Sales,12000,July revenue (reporting month)\n"
    b"2026-07-15,Sales,8000,July revenue #2 later date (reporting month)\n"
    b"2026-07-05,Hosting,-2000,July infra (reporting month)\n"
    b"2026-07-10,Payroll,-15000,July payroll (reporting month)\n"
)


def test_evidence_absent_fields_on_empty_tenant(client, auth_headers, make_auth_headers):
    # No ledger uploaded for this tenant -- NO_DATA response, no evidence
    # field expected (there's nothing to cite yet).
    result = generate_cfo_briefing("EVID-EMPTY-01")
    assert result["status"] == "NO_DATA"
    assert "evidence" not in result


def test_evidence_buckets_match_real_classification(client, make_auth_headers):
    headers = make_auth_headers("EVID-01")
    _upload(client, headers, CSV_BODY)

    result = generate_cfo_briefing("EVID-01")
    assert result["reporting_month"] == "2026-07"
    evidence = result["evidence"]

    # Only the two JULY Sales rows (12000, 8000) count -- June's 10000 row
    # is a real ledger row but belongs to an excluded, non-reporting month.
    assert evidence["revenue"]["total_matching_rows"] == 2
    assert evidence["revenue"]["truncated"] is False
    revenue_amounts = sorted(r["amount"] for r in evidence["revenue"]["shown_rows"])
    assert revenue_amounts == [8000.0, 12000.0]
    # Real row_ids -- never null/fabricated for freshly-ingested rows.
    assert all(r["row_id"] is not None for r in evidence["revenue"]["shown_rows"])

    # Only the JULY Hosting row (-2000) matches the 'hosting' keyword ->
    # cogs. June's Hosting row is excluded by month scoping, not merely
    # deduplicated -- if scoping regressed to a lifetime sum this would be 2.
    assert evidence["cogs"]["total_matching_rows"] == 1
    # Evidence rows carry the REAL signed ledger amount (not the abs value
    # total_cogs itself accumulates) -- a citation should show the actual
    # transaction as it exists in the ledger, not a derived magnitude.
    assert evidence["cogs"]["shown_rows"][0]["amount"] == -2000.0

    # Payroll (-15000) matches no cogs keyword -> opex, exactly one row.
    assert evidence["opex"]["total_matching_rows"] == 1
    assert evidence["opex"]["shown_rows"][0]["amount"] == -15000.0
    assert evidence["opex"]["shown_rows"][0]["category"] == "Payroll"

    # Every row in this test was freshly ingested (real row_id from
    # ledger_row_id_seq) -- nothing legacy/untraceable here.
    assert evidence["legacy_untraceable_rows"] == 0


def test_metrics_scoped_to_reporting_month_not_lifetime_sum(client, make_auth_headers):
    """
    FIN-02/FIN-03's actual point: gross_margin/burn_rate must reflect ONLY
    the reporting month's numbers, not June+July combined. If this
    regressed to a lifetime sum, revenue would be 30000 (10000+12000+8000)
    and burn_rate would be 19000 (2000+2000+15000) instead of the
    July-only figures asserted here.
    """
    headers = make_auth_headers("EVID-05")
    _upload(client, headers, CSV_BODY)

    result = generate_cfo_briefing("EVID-05")
    # July-only: revenue 12000+8000=20000, cogs 2000, opex 15000.
    assert result["metrics"]["gross_margin"] == pytest.approx(((20000 - 2000) / 20000) * 100, abs=0.05)
    assert result["metrics"]["burn_rate"] == pytest.approx(2000 + 15000, abs=0.05)
    assert result["reporting_month"] == "2026-07"
    assert result["reporting_period_note"] == REPORTING_PERIOD_NOTE


def test_evidence_shown_rows_most_recent_first(client, make_auth_headers):
    headers = make_auth_headers("EVID-02")
    _upload(client, headers, CSV_BODY)

    result = generate_cfo_briefing("EVID-02")
    revenue_dates = [r["date"] for r in result["evidence"]["revenue"]["shown_rows"]]
    # Both remaining rows are within the reporting month (July) -- sort is
    # still most-recent-first within that single month: 07-15 before 07-01.
    assert revenue_dates == ["2026-07-15", "2026-07-01"]


def test_evidence_caps_shown_rows_but_reports_real_total(client, make_auth_headers):
    headers = make_auth_headers("EVID-03")
    # 15 distinct Sales rows, all in the same month (Jan 2026) -- more than
    # EVIDENCE_MAX_ROWS_PER_BUCKET (10), so shown_rows must be capped while
    # total_matching_rows stays honest. Single month keeps this test's
    # intent (the cap) independent of month-scoping.
    lines = [f"2026-01-{i+1:02d},Sales,{1000 + i},row {i}" for i in range(15)]
    csv_body = ("date,category,amount,description\n" + "\n".join(lines) + "\n").encode("utf-8")
    _upload(client, headers, csv_body)

    result = generate_cfo_briefing("EVID-03")
    assert result["reporting_month"] == "2026-01"
    revenue = result["evidence"]["revenue"]
    assert revenue["total_matching_rows"] == 15
    assert len(revenue["shown_rows"]) == 10
    assert revenue["truncated"] is True


def test_evidence_present_identically_on_template_fallback_shape(client, make_auth_headers):
    """
    Whether the live-LLM branch or the template-fallback branch produced
    `insights`, the `evidence` field (and the reporting_month/
    reporting_period_note/unparseable_date_rows_excluded fields FIN-02/
    FIN-03 added) must be the SAME real, computed value -- all attached in
    Python after the LLM call (if any) completes or fails, never generated
    by the LLM itself. This asserts the fields exist and have the right
    top-level shape regardless of which branch actually ran during this
    test (nondeterministic given a placeholder OpenAI key), which is
    exactly the guarantee DIFF-09/FIN-02/FIN-03 are supposed to provide.
    """
    headers = make_auth_headers("EVID-04")
    _upload(client, headers, CSV_BODY)
    result = generate_cfo_briefing("EVID-04")

    assert "evidence" in result
    for bucket_key in ("revenue", "cogs", "opex"):
        bucket = result["evidence"][bucket_key]
        assert set(bucket.keys()) == {"total_matching_rows", "shown_rows", "truncated"}
        for row in bucket["shown_rows"]:
            assert set(row.keys()) == {"row_id", "date", "category", "amount"}
    assert "legacy_untraceable_rows" in result["evidence"]
    assert "note" in result["evidence"]
    assert isinstance(result["insights"], list) and len(result["insights"]) > 0

    assert result["reporting_month"] == "2026-07"
    assert result["reporting_period_note"] == REPORTING_PERIOD_NOTE
    assert result["unparseable_date_rows_excluded"] == 0


def test_unparseable_date_rows_excluded_and_counted(client, make_auth_headers):
    """
    FIN-02/FIN-03: a row whose date TRY_CAST(date AS DATE) can't parse
    can't belong to any month, so it must be excluded from every monthly
    figure/evidence bucket -- but its existence must still be disclosed via
    unparseable_date_rows_excluded, not silently dropped with no trace.
    """
    headers = make_auth_headers("EVID-06")
    csv_body = (
        b"date,category,amount,description\n"
        b"2026-07-01,Sales,12000,good date\n"
        b"2026-07-05,Hosting,-2000,good date\n"
        b"not-a-real-date,Sales,99999,BAD date -- must not skew totals\n"
        b"also-bad,Payroll,-88888,BAD date -- must not skew totals\n"
    )
    _upload(client, headers, csv_body)

    result = generate_cfo_briefing("EVID-06")
    assert result["reporting_month"] == "2026-07"
    assert result["unparseable_date_rows_excluded"] == 2
    # The two bad-date rows (99999 revenue, -88888 payroll) must be entirely
    # absent from evidence/totals -- if they leaked in, revenue would be
    # 111999 and opex would include 88888.
    assert result["evidence"]["revenue"]["total_matching_rows"] == 1
    assert result["evidence"]["revenue"]["shown_rows"][0]["amount"] == 12000.0
    assert result["evidence"]["opex"]["total_matching_rows"] == 0


def test_no_dateable_data_status_when_every_row_unparseable(client, make_auth_headers):
    """
    Distinct from the true NO_DATA (empty tenant) status: this tenant DID
    ingest real rows, but not one has a date TRY_CAST can resolve, so no
    calendar month -- and therefore no monthly metric -- can be computed at
    all. Conflating this with NO_DATA would misleadingly imply nothing was
    ever uploaded.
    """
    headers = make_auth_headers("EVID-07")
    csv_body = (
        b"date,category,amount,description\n"
        b"not-a-date,Sales,5000,bad date row 1\n"
        b"still-bad,Hosting,-1000,bad date row 2\n"
    )
    _upload(client, headers, csv_body)

    result = generate_cfo_briefing("EVID-07")
    assert result["status"] == "NO_DATEABLE_DATA"
    assert result["unparseable_date_rows_excluded"] == 2
    assert result["metrics"]["gross_margin"] is None
    assert result["metrics"]["burn_rate"] is None
    assert result["metrics"]["cash_runway_months"] is None
    assert "evidence" not in result
