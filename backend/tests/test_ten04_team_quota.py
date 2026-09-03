"""
TEN-04 (users sub-quota): real per-tenant team-size cap.

Covers the honest slice of TEN-04 that's actually buildable today: a
tenant-self-service max_users quota, enforced at the one real point a
tenant's headcount grows (POST /api/v1/team/invite), plus the
GET/POST/DELETE /api/v1/settings/team-quota endpoints that manage it.
Mirrors FINOPS-01's budget-cap test shape (set/get/clear a per-tenant
optional cap, verify the gate blocks/allows correctly, verify only
owner/admin can change it) applied to team size instead of AI spend.

Deliberately NOT covered here (out of scope for this slice, see
db_manager.py's ALTER-TABLE comment on max_users): storage/rows quotas,
since those need a billing/tier concept that doesn't exist yet.
"""
import pytest


def test_new_tenant_has_no_quota_by_default(client, make_auth_headers):
    """No quota set is the default for every tenant -- unrestricted,
    identical to today's (pre-TEN-04) behavior."""
    owner_headers = make_auth_headers("TENQ-01", role="owner")
    resp = client.get("/api/v1/settings/team-quota", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed"] is True
    assert body["max_users"] is None
    assert body["current_users"] == 1  # just the owner from signup
    assert body["pct_used"] is None


def test_owner_can_set_quota(client, make_auth_headers):
    owner_headers = make_auth_headers("TENQ-02", role="owner")
    resp = client.post("/api/v1/settings/team-quota", json={"max_users": 5}, headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["max_users"] == 5
    assert body["current_users"] == 1
    assert body["allowed"] is True
    assert body["pct_used"] == 20.0


def test_admin_can_set_quota(client, make_auth_headers):
    # make_auth_headers mints a real JWT for this tenant/role directly
    # against the same account-creation path signup/invite use (see its
    # own docstring) -- same pattern the role-parametrized tests below
    # already use to get an admin/member/viewer session with no live
    # invite round trip.
    admin_headers = make_auth_headers("TENQ-03", role="admin")
    resp = client.post("/api/v1/settings/team-quota", json={"max_users": 3}, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["max_users"] == 3


@pytest.mark.parametrize("role", ["member", "viewer"])
def test_non_admin_cannot_set_quota(client, make_auth_headers, role):
    headers = make_auth_headers("TENQ-04", role=role)
    resp = client.post("/api/v1/settings/team-quota", json={"max_users": 5}, headers=headers)
    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize("role", ["member", "viewer"])
def test_any_role_can_view_quota_status(client, make_auth_headers, role):
    """GET is not a sensitive operation on its own -- same call as GET
    /api/v1/team/users (any authenticated teammate can see it)."""
    headers = make_auth_headers("TENQ-05", role=role)
    resp = client.get("/api/v1/settings/team-quota", headers=headers)
    assert resp.status_code == 200, resp.text


def test_quota_at_headcount_blocks_further_invites(client, make_auth_headers):
    owner_headers = make_auth_headers("TENQ-06", role="owner")
    # Tenant currently has 1 user (the owner) -- a quota of 1 means no
    # room for a second.
    client.post("/api/v1/settings/team-quota", json={"max_users": 1}, headers=owner_headers)

    resp = client.post(
        "/api/v1/team/invite",
        json={"email": "tenq06-blocked@test.example", "role": "member"},
        headers=owner_headers,
    )
    assert resp.status_code == 409, resp.text
    assert "quota" in resp.json()["detail"].lower()
    assert "1" in resp.json()["detail"]

    # And the user genuinely was never created -- not just a blocked
    # response with a silent side effect.
    login_attempt = client.post(
        "/api/v1/auth/login",
        json={"email": "tenq06-blocked@test.example", "password": "whatever12345"},
    )
    assert login_attempt.status_code == 401


def test_quota_above_headcount_allows_invite(client, make_auth_headers):
    owner_headers = make_auth_headers("TENQ-07", role="owner")
    client.post("/api/v1/settings/team-quota", json={"max_users": 2}, headers=owner_headers)

    resp = client.post(
        "/api/v1/team/invite",
        json={"email": "tenq07-allowed@test.example", "role": "member"},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text

    # Now at 2/2 -- the NEXT invite must be blocked.
    resp2 = client.post(
        "/api/v1/team/invite",
        json={"email": "tenq07-second@test.example", "role": "member"},
        headers=owner_headers,
    )
    assert resp2.status_code == 409, resp2.text


def test_removing_teammate_frees_a_quota_slot(client, make_auth_headers):
    owner_headers = make_auth_headers("TENQ-08", role="owner")
    client.post("/api/v1/settings/team-quota", json={"max_users": 2}, headers=owner_headers)

    invite = client.post(
        "/api/v1/team/invite",
        json={"email": "tenq08-member@test.example", "role": "member"},
        headers=owner_headers,
    )
    assert invite.status_code == 200, invite.text
    member_user_id = invite.json()["user_id"]

    # At 2/2 -- blocked.
    blocked = client.post(
        "/api/v1/team/invite",
        json={"email": "tenq08-blocked@test.example", "role": "member"},
        headers=owner_headers,
    )
    assert blocked.status_code == 409

    # Remove the teammate -- real current headcount drops back to 1.
    removed = client.delete(f"/api/v1/team/users/{member_user_id}", headers=owner_headers)
    assert removed.status_code == 200, removed.text

    status = client.get("/api/v1/settings/team-quota", headers=owner_headers)
    assert status.json()["current_users"] == 1
    assert status.json()["allowed"] is True

    # The freed slot is real -- a new invite now succeeds.
    allowed_now = client.post(
        "/api/v1/team/invite",
        json={"email": "tenq08-newmember@test.example", "role": "member"},
        headers=owner_headers,
    )
    assert allowed_now.status_code == 200, allowed_now.text


def test_deleting_quota_clears_it_back_to_unrestricted(client, make_auth_headers):
    owner_headers = make_auth_headers("TENQ-09", role="owner")
    client.post("/api/v1/settings/team-quota", json={"max_users": 1}, headers=owner_headers)

    # Confirm the gate really is up.
    blocked = client.post(
        "/api/v1/team/invite",
        json={"email": "tenq09-blocked@test.example", "role": "member"},
        headers=owner_headers,
    )
    assert blocked.status_code == 409

    delete_resp = client.delete("/api/v1/settings/team-quota", headers=owner_headers)
    assert delete_resp.status_code == 200, delete_resp.text
    assert delete_resp.json()["max_users"] is None
    assert delete_resp.json()["allowed"] is True

    # The gate should now be down again, regardless of headcount.
    unblocked = client.post(
        "/api/v1/team/invite",
        json={"email": "tenq09-unblocked@test.example", "role": "member"},
        headers=owner_headers,
    )
    assert unblocked.status_code == 200, unblocked.text


def test_quota_rejects_non_positive_values(client, make_auth_headers):
    owner_headers = make_auth_headers("TENQ-10", role="owner")
    resp = client.post("/api/v1/settings/team-quota", json={"max_users": 0}, headers=owner_headers)
    assert resp.status_code == 422, resp.text

    resp2 = client.post("/api/v1/settings/team-quota", json={"max_users": -3}, headers=owner_headers)
    assert resp2.status_code == 422, resp2.text


def test_quota_is_tenant_isolated(client, make_auth_headers):
    """Setting tenant A's quota to 1 (already at capacity) must never
    affect tenant B's ability to invite -- each tenant's headcount and
    quota are scoped by client_id independently (db_manager.
    check_user_quota_gate takes client_id, never a global)."""
    owner_a = make_auth_headers("TENQ-11-A", role="owner")
    owner_b = make_auth_headers("TENQ-11-B", role="owner")

    client.post("/api/v1/settings/team-quota", json={"max_users": 1}, headers=owner_a)

    # Tenant A is now blocked...
    blocked_a = client.post(
        "/api/v1/team/invite",
        json={"email": "tenq11a-blocked@test.example", "role": "member"},
        headers=owner_a,
    )
    assert blocked_a.status_code == 409

    # ...but tenant B (no quota set) is completely unaffected.
    allowed_b = client.post(
        "/api/v1/team/invite",
        json={"email": "tenq11b-allowed@test.example", "role": "member"},
        headers=owner_b,
    )
    assert allowed_b.status_code == 200, allowed_b.text

    status_b = client.get("/api/v1/settings/team-quota", headers=owner_b)
    assert status_b.json()["max_users"] is None
    assert status_b.json()["current_users"] == 2


def test_unauthenticated_requests_rejected(client):
    """No token at all on any of the three team-quota routes -> 401/403,
    same shape QA-02's suite already holds every other protected route to
    (this file focuses on TEN-04's real behavior, not re-deriving QA-02's
    full introspective sweep -- that suite will pick these routes up on
    its own next run, see this file's own count-bump in
    test_qa02_authz_regression.py)."""
    assert client.get("/api/v1/settings/team-quota").status_code in (401, 403)
    assert client.post("/api/v1/settings/team-quota", json={"max_users": 5}).status_code in (401, 403)
    assert client.delete("/api/v1/settings/team-quota").status_code in (401, 403)
