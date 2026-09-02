"""
REP-01/REP-02 (28 Aug 2026): real CSV/PDF export of the stakeholder
report, plus the export audit trail. Before this, /api/v1/reports/
stakeholder always returned JSON only -- nothing a stakeholder could
actually download. These tests exercise the new endpoints end-to-end
through the real client fixture (real ledger upload -> real report
generation -> real file bytes back), not just at the render-function
level, so a wiring mistake (wrong dependency, wrong content-type, wrong
audit call) would show up here.
"""
import io

import duckdb
import pytest


def _upload_real_ledger(client, headers):
    csv_content = (
        b"date,category,amount,description\n"
        b"2026-01-05,Sales,10000,Big client payment\n"
        b"2026-01-10,Rent,-2000,Office rent\n"
        b"2026-01-15,Sales,5000,Second client payment\n"
    )
    resp = client.post(
        "/api/finance/upload-ledger",
        files={"file": ("export_test_ledger.csv", io.BytesIO(csv_content), "text/csv")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def test_export_csv_returns_real_downloadable_csv(client, make_auth_headers):
    headers = make_auth_headers("REP01-CSV-TENANT")
    _upload_real_ledger(client, headers)

    resp = client.get("/api/v1/reports/stakeholder/export?format=csv", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    assert ".csv" in resp.headers["content-disposition"]

    text = resp.content.decode("utf-8")
    assert "Total Revenue" in text
    # 10000 + 5000 = 15000 revenue -- the real ingested numbers, not a
    # placeholder or fabricated figure.
    assert "$15,000.00" in text


def test_export_pdf_returns_real_downloadable_pdf(client, make_auth_headers):
    headers = make_auth_headers("REP01-PDF-TENANT")
    _upload_real_ledger(client, headers)

    resp = client.get("/api/v1/reports/stakeholder/export?format=pdf", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers["content-disposition"]
    assert ".pdf" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")

    import pdfplumber
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "Total Revenue" in full_text
    assert "$15,000.00" in full_text
    assert "REP01-PDF-TENANT" in full_text  # tenant id shown in the metadata line


def test_export_rejects_unsupported_format(client, make_auth_headers):
    headers = make_auth_headers("REP01-BADFORMAT-TENANT")
    resp = client.get("/api/v1/reports/stakeholder/export?format=xml", headers=headers)
    assert resp.status_code == 400


def test_export_requires_format_param(client, make_auth_headers):
    headers = make_auth_headers("REP01-NOFORMAT-TENANT")
    resp = client.get("/api/v1/reports/stakeholder/export", headers=headers)
    assert resp.status_code == 422  # FastAPI's own required-query-param validation


def test_export_with_no_ledger_data_still_returns_valid_file(client, make_auth_headers):
    """A brand-new tenant with zero ledger rows must still get a real,
    valid downloadable file (the NO_DATA status), not a crash or a 500."""
    headers = make_auth_headers("REP01-EMPTY-TENANT")
    resp = client.get("/api/v1/reports/stakeholder/export?format=csv", headers=headers)
    assert resp.status_code == 200
    text = resp.content.decode("utf-8")
    assert "NO_DATA" in text

    resp_pdf = client.get("/api/v1/reports/stakeholder/export?format=pdf", headers=headers)
    assert resp_pdf.status_code == 200
    assert resp_pdf.content.startswith(b"%PDF")


def test_export_writes_success_audit_row(client, make_auth_headers, isolated_db):
    headers = make_auth_headers("REP01-AUDIT-TENANT")
    _upload_real_ledger(client, headers)

    resp = client.get("/api/v1/reports/stakeholder/export?format=csv", headers=headers)
    assert resp.status_code == 200

    conn = duckdb.connect(isolated_db.DB_PATH)
    try:
        rows = conn.execute(
            "SELECT client_id, report_type, export_format, status FROM report_export_audit "
            "WHERE client_id = ?", ["REP01-AUDIT-TENANT"]
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0] == ("REP01-AUDIT-TENANT", "stakeholder", "csv", "SUCCESS")


def test_export_history_visible_to_owner(client, make_auth_headers):
    headers = make_auth_headers("REP01-HISTORY-TENANT")
    _upload_real_ledger(client, headers)
    client.get("/api/v1/reports/stakeholder/export?format=csv", headers=headers)
    client.get("/api/v1/reports/stakeholder/export?format=pdf", headers=headers)

    resp = client.get("/api/v1/reports/export-history", headers=headers)
    assert resp.status_code == 200
    exports = resp.json()["exports"]
    assert len(exports) == 2
    formats = {e["export_format"] for e in exports}
    assert formats == {"csv", "pdf"}
    assert all(e["status"] == "SUCCESS" for e in exports)


def test_export_history_forbidden_for_member_role(client, make_auth_headers):
    headers = make_auth_headers("REP01-MEMBER-TENANT", role="member")
    resp = client.get("/api/v1/reports/export-history", headers=headers)
    assert resp.status_code == 403


def test_export_history_empty_for_tenant_with_no_exports(client, make_auth_headers):
    headers = make_auth_headers("REP01-NOEXPORT-TENANT")
    resp = client.get("/api/v1/reports/export-history", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["exports"] == []


def test_export_is_tenant_scoped_not_cross_tenant(client, make_auth_headers):
    """Tenant A's exported numbers must reflect only tenant A's ledger,
    never tenant B's, even though both hit the same endpoint."""
    headers_a = make_auth_headers("REP01-ISO-A")
    headers_b = make_auth_headers("REP01-ISO-B")
    _upload_real_ledger(client, headers_a)  # A: $15,000 revenue

    csv_b = (
        b"date,category,amount,description\n"
        b"2026-01-05,Sales,999,Tenant B sale\n"
    )
    resp = client.post(
        "/api/finance/upload-ledger",
        files={"file": ("b_ledger.csv", io.BytesIO(csv_b), "text/csv")},
        headers=headers_b,
    )
    assert resp.status_code == 200

    resp_a = client.get("/api/v1/reports/stakeholder/export?format=csv", headers=headers_a)
    resp_b = client.get("/api/v1/reports/stakeholder/export?format=csv", headers=headers_b)
    text_a = resp_a.content.decode("utf-8")
    text_b = resp_b.content.decode("utf-8")

    assert "$15,000.00" in text_a
    assert "$999.00" not in text_a
    assert "$999.00" in text_b
    assert "$15,000.00" not in text_b
