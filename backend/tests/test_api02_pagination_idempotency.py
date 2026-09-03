"""
API-02: real pagination/filtering/sorting on the three endpoints whose
result set can grow unbounded per tenant (ingestion history, audit
lineage, report export history), plus a real opt-in Idempotency-Key
mechanism on the two POST endpoints most exposed to silent double-
creation on retry (team invite, API key creation).

Pagination coverage deliberately checks the envelope's own math
(total_count/has_more/offset) against real row counts, not just that a
`limit` truncates the list -- and checks the pre-existing response key
("history"/"entries"/"exports") still holds the same array shape as
before this item shipped, so no existing frontend consumer breaks.

Idempotency coverage checks the property that actually matters: a
replayed request returns the SAME resource (same user_id / same raw
api_key) rather than a second, distinct one -- verified by an
independent roster/list count, not just a matching response body.
"""
import asyncio
import io

import pytest


# ---------------------------------------------------------------------
# Ingestion history (DATA-08) pagination/filtering/sorting
# ---------------------------------------------------------------------

def _upload(client, headers, filename, good=True):
    if good:
        body = f"date,category,amount,description\n2026-01-05,Sales,100,{filename}\n".encode()
    else:
        body = b"not,a,valid,csv,header\ngarbage\n"
    return client.post(
        "/api/finance/upload-ledger",
        files={"file": (filename, io.BytesIO(body), "text/csv")},
        headers=headers,
    )


def test_ingestion_history_pagination_math_and_backward_compatible_key(client, make_auth_headers):
    headers = make_auth_headers("API02-ING-01", role="owner")
    for i in range(5):
        _upload(client, headers, f"good{i}.csv", good=True)

    page1 = client.get("/api/v1/data/ingestion-history?limit=2&offset=0", headers=headers).json()
    assert len(page1["history"]) == 2
    assert page1["total_count"] == 5
    assert page1["limit"] == 2
    assert page1["offset"] == 0
    assert page1["has_more"] is True

    page3 = client.get("/api/v1/data/ingestion-history?limit=2&offset=4", headers=headers).json()
    assert len(page3["history"]) == 1
    assert page3["has_more"] is False

    # Pages don't overlap -- offset=0 and offset=2 return disjoint rows.
    page2 = client.get("/api/v1/data/ingestion-history?limit=2&offset=2", headers=headers).json()
    filenames_1 = {h["filename"] for h in page1["history"]}
    filenames_2 = {h["filename"] for h in page2["history"]}
    assert filenames_1.isdisjoint(filenames_2)


def test_ingestion_history_status_filter(client, make_auth_headers):
    headers = make_auth_headers("API02-ING-02", role="owner")
    _upload(client, headers, "good.csv", good=True)
    _upload(client, headers, "bad.csv", good=False)

    rejected = client.get("/api/v1/data/ingestion-history?status=REJECTED", headers=headers).json()
    assert rejected["total_count"] == 1
    assert all(h["status"] == "REJECTED" for h in rejected["history"])

    success = client.get("/api/v1/data/ingestion-history?status=SUCCESS", headers=headers).json()
    assert success["total_count"] == 1
    assert all(h["status"] == "SUCCESS" for h in success["history"])


def test_ingestion_history_sort_direction(client, make_auth_headers):
    headers = make_auth_headers("API02-ING-03", role="owner")
    _upload(client, headers, "first.csv")
    _upload(client, headers, "second.csv")
    _upload(client, headers, "third.csv")

    desc = client.get("/api/v1/data/ingestion-history?sort=desc", headers=headers).json()["history"]
    asc = client.get("/api/v1/data/ingestion-history?sort=asc", headers=headers).json()["history"]
    assert [h["filename"] for h in desc] == list(reversed([h["filename"] for h in asc]))


# ---------------------------------------------------------------------
# Audit lineage (ENT-03) pagination/filtering/sorting
# ---------------------------------------------------------------------

def _seed_lineage(isolated_db, client_id, agent_name, count):
    async def _seed():
        for i in range(count):
            await isolated_db.log_lineage_entry(
                client_id, agent_name, f"query {i}", f"decision {i}", "SUCCESS",
            )
    asyncio.run(_seed())


def test_audit_lineage_pagination_and_backward_compatible_key(client, make_auth_headers, isolated_db):
    headers = make_auth_headers("API02-LIN-01", role="owner")
    _seed_lineage(isolated_db, "API02-LIN-01", "bi_engineer", 5)

    page = client.get("/api/v1/audit/lineage?limit=2&offset=0", headers=headers).json()
    assert len(page["entries"]) == 2
    assert page["total_count"] == 5
    assert page["has_more"] is True
    assert "integrity" in page  # untouched by paging -- still checks the FULL chain


def test_audit_lineage_agent_name_filter(client, make_auth_headers, isolated_db):
    headers = make_auth_headers("API02-LIN-02", role="owner")
    _seed_lineage(isolated_db, "API02-LIN-02", "bi_engineer", 3)
    _seed_lineage(isolated_db, "API02-LIN-02", "predictive_forecaster", 2)

    bi_only = client.get("/api/v1/audit/lineage?agent_name=bi_engineer", headers=headers).json()
    assert bi_only["total_count"] == 3
    assert all(e["agent_name"] == "bi_engineer" for e in bi_only["entries"])

    forecaster_only = client.get(
        "/api/v1/audit/lineage?agent_name=predictive_forecaster", headers=headers
    ).json()
    assert forecaster_only["total_count"] == 2


def test_audit_lineage_is_tenant_isolated_for_pagination(client, make_auth_headers, isolated_db):
    """Tenant A's total_count/entries must never include tenant B's rows,
    even though both call the same endpoint with the same query shape."""
    headers_a = make_auth_headers("API02-LIN-03-A", role="owner")
    headers_b = make_auth_headers("API02-LIN-03-B", role="owner")
    _seed_lineage(isolated_db, "API02-LIN-03-A", "bi_engineer", 4)
    _seed_lineage(isolated_db, "API02-LIN-03-B", "bi_engineer", 1)

    page_a = client.get("/api/v1/audit/lineage", headers=headers_a).json()
    page_b = client.get("/api/v1/audit/lineage", headers=headers_b).json()
    assert page_a["total_count"] == 4
    assert page_b["total_count"] == 1


# ---------------------------------------------------------------------
# Report export history (REP-02) pagination/filtering/sorting
# ---------------------------------------------------------------------

def _upload_and_export(client, headers, fmt):
    csv_content = b"date,category,amount,description\n2026-01-05,Sales,10000,Payment\n"
    client.post(
        "/api/finance/upload-ledger",
        files={"file": ("ledger.csv", io.BytesIO(csv_content), "text/csv")},
        headers=headers,
    )
    return client.get(f"/api/v1/reports/stakeholder/export?format={fmt}", headers=headers)


def test_export_history_pagination_and_backward_compatible_key(client, make_auth_headers):
    headers = make_auth_headers("API02-EXP-01", role="owner")
    for fmt in ["csv", "pdf", "csv"]:
        resp = _upload_and_export(client, headers, fmt)
        assert resp.status_code == 200, resp.text

    page = client.get("/api/v1/reports/export-history?limit=2&offset=0", headers=headers).json()
    assert len(page["exports"]) == 2
    assert page["total_count"] == 3
    assert page["has_more"] is True


def test_export_history_format_filter(client, make_auth_headers):
    headers = make_auth_headers("API02-EXP-02", role="owner")
    _upload_and_export(client, headers, "csv")
    _upload_and_export(client, headers, "pdf")

    csv_only = client.get("/api/v1/reports/export-history?export_format=csv", headers=headers).json()
    assert csv_only["total_count"] == 1
    assert csv_only["exports"][0]["export_format"] == "csv"


# ---------------------------------------------------------------------
# Idempotency: POST /api/v1/team/invite
# ---------------------------------------------------------------------

def test_invite_replay_returns_same_user_not_a_second_one(client, make_auth_headers):
    owner_headers = make_auth_headers("API02-IDEM-01", role="owner")
    idem_headers = {**owner_headers, "Idempotency-Key": "invite-key-abc-123"}
    body = {"email": "api02-idem-01-member@test.example", "role": "member"}

    first = client.post("/api/v1/team/invite", json=body, headers=idem_headers)
    assert first.status_code == 200, first.text
    first_body = first.json()

    replay = client.post("/api/v1/team/invite", json=body, headers=idem_headers)
    assert replay.status_code == 200, replay.text
    replay_body = replay.json()

    # Same resource, not a re-execution -- same user_id and same
    # temp_password (create_invited_user was never called a second time).
    assert replay_body["user_id"] == first_body["user_id"]
    assert replay_body["temp_password"] == first_body["temp_password"]

    roster = client.get("/api/v1/team/users", headers=owner_headers).json()["users"]
    matching = [u for u in roster if u["email"] == "api02-idem-01-member@test.example"]
    assert len(matching) == 1, "Replay must not have created a second teammate."


def test_invite_same_key_different_body_rejected(client, make_auth_headers):
    owner_headers = make_auth_headers("API02-IDEM-02", role="owner")
    idem_headers = {**owner_headers, "Idempotency-Key": "invite-key-reused"}

    first = client.post(
        "/api/v1/team/invite",
        json={"email": "api02-idem-02-a@test.example", "role": "member"},
        headers=idem_headers,
    )
    assert first.status_code == 200, first.text

    conflicting = client.post(
        "/api/v1/team/invite",
        json={"email": "api02-idem-02-b@test.example", "role": "viewer"},
        headers=idem_headers,
    )
    assert conflicting.status_code == 422, conflicting.text
    assert "idempotency" in conflicting.json()["detail"].lower()


def test_invite_without_idempotency_key_behaves_exactly_as_before(client, make_auth_headers):
    """No header at all -- two calls with the same body must be free to
    behave exactly as they did before API-02: the second one hits the
    real duplicate-email 409, not a silent replay."""
    owner_headers = make_auth_headers("API02-IDEM-03", role="owner")
    body = {"email": "api02-idem-03-member@test.example", "role": "member"}

    first = client.post("/api/v1/team/invite", json=body, headers=owner_headers)
    assert first.status_code == 200, first.text

    second = client.post("/api/v1/team/invite", json=body, headers=owner_headers)
    assert second.status_code == 409, second.text


def test_invite_idempotency_key_scoped_per_tenant(client, make_auth_headers):
    """The SAME literal key value used by two different tenants must
    never collide -- each tenant's invite is independent."""
    owner_a = make_auth_headers("API02-IDEM-04-A", role="owner")
    owner_b = make_auth_headers("API02-IDEM-04-B", role="owner")
    shared_key = "same-literal-key-both-tenants"

    resp_a = client.post(
        "/api/v1/team/invite",
        json={"email": "api02-idem-04-a-member@test.example", "role": "member"},
        headers={**owner_a, "Idempotency-Key": shared_key},
    )
    resp_b = client.post(
        "/api/v1/team/invite",
        json={"email": "api02-idem-04-b-member@test.example", "role": "member"},
        headers={**owner_b, "Idempotency-Key": shared_key},
    )
    assert resp_a.status_code == 200, resp_a.text
    assert resp_b.status_code == 200, resp_b.text
    assert resp_a.json()["user_id"] != resp_b.json()["user_id"]


# ---------------------------------------------------------------------
# Idempotency: POST /api/v1/settings/api-keys
# ---------------------------------------------------------------------

def test_api_key_replay_returns_same_raw_key_not_a_second_one(client, make_auth_headers):
    owner_headers = make_auth_headers("API02-IDEM-05", role="owner")
    idem_headers = {**owner_headers, "Idempotency-Key": "apikey-create-key-1"}
    body = {"label": "ci-pipeline"}

    first = client.post("/api/v1/settings/api-keys", json=body, headers=idem_headers)
    assert first.status_code == 200, first.text
    first_body = first.json()

    replay = client.post("/api/v1/settings/api-keys", json=body, headers=idem_headers)
    assert replay.status_code == 200, replay.text
    replay_body = replay.json()

    # The raw secret is only ever shown once by design -- a genuine
    # replay must return that SAME secret again, not mint (and silently
    # orphan) a second one.
    assert replay_body["api_key"] == first_body["api_key"]
    assert replay_body["key_id"] == first_body["key_id"]

    keys = client.get("/api/v1/settings/api-keys", headers=owner_headers).json()["api_keys"]
    matching = [k for k in keys if k["key_id"] == first_body["key_id"]]
    assert len(matching) == 1
    assert len(keys) == 1, "Replay must not have minted a second key."


def test_api_key_same_key_different_label_rejected(client, make_auth_headers):
    owner_headers = make_auth_headers("API02-IDEM-06", role="owner")
    idem_headers = {**owner_headers, "Idempotency-Key": "apikey-reused-key"}

    first = client.post("/api/v1/settings/api-keys", json={"label": "label-a"}, headers=idem_headers)
    assert first.status_code == 200, first.text

    conflicting = client.post("/api/v1/settings/api-keys", json={"label": "label-b"}, headers=idem_headers)
    assert conflicting.status_code == 422, conflicting.text


def test_api_key_without_idempotency_key_creates_two_distinct_keys(client, make_auth_headers):
    """No header -- unchanged pre-API-02 behavior: two identical create
    calls make two genuinely distinct keys."""
    owner_headers = make_auth_headers("API02-IDEM-07", role="owner")
    body = {"label": "same-label-twice"}

    first = client.post("/api/v1/settings/api-keys", json=body, headers=owner_headers)
    second = client.post("/api/v1/settings/api-keys", json=body, headers=owner_headers)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["api_key"] != second.json()["api_key"]
    assert first.json()["key_id"] != second.json()["key_id"]
