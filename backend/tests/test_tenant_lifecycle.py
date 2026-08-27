"""
TEN-01/TEN-02/TEN-03: tenant lifecycle -- manual owner-triggered
suspend/reactivate, full data export, and permanent cascading delete.

Suspension is deliberately NOT subscription-driven (no billing exists yet
-- see the Master Build List's own note on why that half of TEN-02 stays
open). The suspension GATE itself (backend/auth.py's
_raise_if_suspended, wired into verify_jwt_and_get_user and therefore
require_role) is what these tests are really about: every OTHER
protected endpoint in the app should 423 once a tenant is suspended,
while a narrow, explicit set of tenant-lifecycle endpoints
(status/reactivate/export/delete) must keep working regardless, or a
suspended owner would have no way back in.
"""
import asyncio
import io

import pytest


def _upload(client, auth_headers, csv_body: bytes = None):
    csv_body = csv_body or (
        b"date,category,amount,description\n"
        b"2026-07-01,Sales,5000,test revenue\n"
    )
    resp = client.post(
        "/api/finance/upload-ledger",
        files={"file": ("ledger.csv", io.BytesIO(csv_body), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text


def test_suspend_as_owner_sets_status(client, make_auth_headers):
    owner_headers = make_auth_headers("TEN-01", role="owner")
    resp = client.post("/api/v1/tenant/suspend", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["lifecycle_status"] == "suspended"
    assert body["suspended_at"] is not None
    assert body["suspended_by_email"] == "ten-01-owner@test.example"


@pytest.mark.parametrize("role", ["admin", "member", "viewer"])
def test_suspend_as_non_owner_forbidden(client, make_auth_headers, role):
    headers = make_auth_headers("TEN-02", role=role)
    resp = client.post("/api/v1/tenant/suspend", headers=headers)
    assert resp.status_code == 403, resp.text


def test_suspended_tenant_blocks_other_protected_endpoints(client, make_auth_headers):
    owner_headers = make_auth_headers("TEN-03", role="owner")
    client.post("/api/v1/tenant/suspend", headers=owner_headers)

    # Any ordinary protected endpoint (team roster, in this case) must now
    # 423 -- this is the whole point of the suspension gate: it protects
    # the WHOLE app via verify_jwt_and_get_user/require_role, not just one
    # hand-picked endpoint.
    resp = client.get("/api/v1/team/users", headers=owner_headers)
    assert resp.status_code == 423, resp.text
    assert "suspended" in resp.json()["detail"].lower()


def test_reactivate_as_owner_while_suspended_works(client, make_auth_headers):
    owner_headers = make_auth_headers("TEN-04", role="owner")
    client.post("/api/v1/tenant/suspend", headers=owner_headers)

    # Confirm the gate really is up first.
    blocked = client.get("/api/v1/team/users", headers=owner_headers)
    assert blocked.status_code == 423

    resp = client.post("/api/v1/tenant/reactivate", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["lifecycle_status"] == "active"
    assert resp.json()["suspended_at"] is None

    # The gate should now be down again.
    unblocked = client.get("/api/v1/team/users", headers=owner_headers)
    assert unblocked.status_code == 200, unblocked.text


def test_reactivate_as_non_owner_forbidden_not_gated(client, make_auth_headers):
    """
    A non-owner calling reactivate while suspended must get 403 (role
    check), not 423 (suspension gate) -- proving require_role_allow_
    suspended really does bypass the gate before checking role, rather
    than the gate happening to not matter here for some other reason.
    """
    owner_headers = make_auth_headers("TEN-05", role="owner")
    member_headers = make_auth_headers("TEN-05", role="member")
    client.post("/api/v1/tenant/suspend", headers=owner_headers)

    resp = client.post("/api/v1/tenant/reactivate", headers=member_headers)
    assert resp.status_code == 403, resp.text


def test_me_works_while_suspended_and_reports_status(client, make_auth_headers):
    owner_headers = make_auth_headers("TEN-06", role="owner")
    client.post("/api/v1/tenant/suspend", headers=owner_headers)

    resp = client.get("/api/v1/auth/me", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tenant_suspended"] is True
    assert body["lifecycle_status"] == "suspended"


def test_login_and_signup_report_lifecycle_fields(client, isolated_db):
    signup_resp = client.post("/api/v1/auth/signup", json={
        "company_name": "Lifecycle Field Co",
        "email": "lifecycle-signup@test.example",
        "password": "correct-horse-battery",
    })
    assert signup_resp.status_code == 200, signup_resp.text
    body = signup_resp.json()
    assert body["lifecycle_status"] == "active"
    assert body["tenant_suspended"] is False

    login_resp = client.post("/api/v1/auth/login", json={
        "email": "lifecycle-signup@test.example",
        "password": "correct-horse-battery",
    })
    assert login_resp.status_code == 200, login_resp.text
    login_body = login_resp.json()
    assert login_body["lifecycle_status"] == "active"
    assert login_body["tenant_suspended"] is False


@pytest.mark.parametrize("role", ["owner", "admin", "member", "viewer"])
def test_tenant_status_any_role_works_while_suspended(client, make_auth_headers, role):
    owner_headers = make_auth_headers("TEN-07", role="owner")
    role_headers = make_auth_headers("TEN-07", role=role)
    client.post("/api/v1/tenant/suspend", headers=owner_headers)

    resp = client.get("/api/v1/tenant/status", headers=role_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["lifecycle_status"] == "suspended"


def test_export_owner_and_admin_allowed_member_forbidden(client, make_auth_headers):
    owner_headers = make_auth_headers("TEN-08", role="owner")
    admin_headers = make_auth_headers("TEN-08", role="admin")
    member_headers = make_auth_headers("TEN-08", role="member")
    _upload(client, owner_headers)

    owner_resp = client.get("/api/v1/tenant/export", headers=owner_headers)
    assert owner_resp.status_code == 200, owner_resp.text

    admin_resp = client.get("/api/v1/tenant/export", headers=admin_headers)
    assert admin_resp.status_code == 200, admin_resp.text

    member_resp = client.get("/api/v1/tenant/export", headers=member_headers)
    assert member_resp.status_code == 403, member_resp.text


def test_export_shape_and_secret_exclusion(client, make_auth_headers):
    owner_headers = make_auth_headers("TEN-09", role="owner")
    _upload(client, owner_headers, (
        b"date,category,amount,description\n"
        b"2026-07-01,Sales,7500,export test row\n"
    ))

    resp = client.get("/api/v1/tenant/export", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["tenant"]["client_id"] == "TEN-09"
    assert data["tenant"]["lifecycle_status"] == "active"
    assert len(data["ledgers"]) == 1
    assert data["ledgers"][0]["amount"] == 7500.0

    assert len(data["users"]) >= 1
    for user_row in data["users"]:
        assert "password_hash" not in user_row

    # api_keys list may be empty in this test (none created), but if
    # present must never carry the hash or prefix.
    for key_row in data.get("api_keys", []):
        assert "key_hash" not in key_row
        assert "key_prefix" not in key_row


def test_export_works_while_suspended(client, make_auth_headers):
    owner_headers = make_auth_headers("TEN-10", role="owner")
    _upload(client, owner_headers)
    client.post("/api/v1/tenant/suspend", headers=owner_headers)

    resp = client.get("/api/v1/tenant/export", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["ledgers"]) == 1


def test_delete_wrong_confirmation_rejected_and_nothing_deleted(client, make_auth_headers, isolated_db):
    owner_headers = make_auth_headers("TEN-11", role="owner")
    _upload(client, owner_headers)

    resp = client.request(
        "DELETE", "/api/v1/tenant",
        headers=owner_headers,
        json={"confirm_company_name": "Definitely The Wrong Name"},
    )
    assert resp.status_code == 400, resp.text

    # Confirm nothing was actually touched -- the tenant and its ledger
    # row are both still there.
    tenant = asyncio.run(isolated_db.get_tenant("TEN-11"))
    assert tenant is not None
    export_resp = client.get("/api/v1/tenant/export", headers=owner_headers)
    assert len(export_resp.json()["ledgers"]) == 1


def test_delete_correct_confirmation_removes_everything(client, make_auth_headers, isolated_db):
    owner_headers = make_auth_headers("TEN-12", role="owner")
    _upload(client, owner_headers)

    # make_auth_headers creates real tenants via create_tenant_and_owner
    # with company_name f"Test Tenant {client_id}" -- see conftest.py.
    resp = client.request(
        "DELETE", "/api/v1/tenant",
        headers=owner_headers,
        json={"confirm_company_name": "Test Tenant TEN-12"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] is True
    assert body["counts"]["ledgers"] == 1
    assert body["counts"]["users"] == 1

    # Real, permanent: the tenant row itself is gone.
    tenant = asyncio.run(isolated_db.get_tenant("TEN-12"))
    assert tenant is None
    # And so is the user who owned it -- a fresh lookup by email finds nothing.
    user = asyncio.run(isolated_db.get_user_by_email("ten-12-owner@test.example"))
    assert user is None


@pytest.mark.parametrize("role", ["admin", "member", "viewer"])
def test_delete_as_non_owner_forbidden(client, make_auth_headers, isolated_db, role):
    make_auth_headers("TEN-13", role="owner")
    role_headers = make_auth_headers("TEN-13", role=role)

    resp = client.request(
        "DELETE", "/api/v1/tenant",
        headers=role_headers,
        json={"confirm_company_name": "Test Tenant TEN-13"},
    )
    assert resp.status_code == 403, resp.text
    tenant = asyncio.run(isolated_db.get_tenant("TEN-13"))
    assert tenant is not None


def test_delete_works_while_suspended(client, make_auth_headers, isolated_db):
    owner_headers = make_auth_headers("TEN-14", role="owner")
    client.post("/api/v1/tenant/suspend", headers=owner_headers)

    resp = client.request(
        "DELETE", "/api/v1/tenant",
        headers=owner_headers,
        json={"confirm_company_name": "Test Tenant TEN-14"},
    )
    assert resp.status_code == 200, resp.text
    tenant = asyncio.run(isolated_db.get_tenant("TEN-14"))
    assert tenant is None


def test_cross_tenant_isolation_suspend_does_not_affect_other_tenant(client, make_auth_headers):
    owner_a = make_auth_headers("TEN-15-A", role="owner")
    owner_b = make_auth_headers("TEN-15-B", role="owner")

    client.post("/api/v1/tenant/suspend", headers=owner_a)

    # Tenant A is blocked...
    a_blocked = client.get("/api/v1/team/users", headers=owner_a)
    assert a_blocked.status_code == 423

    # ...but tenant B is completely unaffected.
    b_ok = client.get("/api/v1/team/users", headers=owner_b)
    assert b_ok.status_code == 200, b_ok.text
    b_status = client.get("/api/v1/tenant/status", headers=owner_b)
    assert b_status.json()["lifecycle_status"] == "active"
