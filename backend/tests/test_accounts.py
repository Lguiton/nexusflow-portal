"""
RBAC-01: real coverage for backend/accounts.py's team-management endpoints
-- invite, list, role change, removal. Signup/login themselves are covered
in test_api_endpoints.py alongside the rest of the HTTP layer; this file
is specifically about the owner/admin-gated team actions layered on top.
"""


def test_owner_can_invite_member(client, make_auth_headers):
    owner_headers = make_auth_headers("CLI-INVITE-01", role="owner")
    resp = client.post(
        "/api/v1/team/invite",
        json={"email": "newmember@test.example", "role": "member"},
        headers=owner_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "member"
    assert body["email"] == "newmember@test.example"
    # Temp password is real and usable -- see the invited user's own
    # login round trip below, not just returned-but-unverified.
    assert isinstance(body["temp_password"], str) and len(body["temp_password"]) >= 12


def test_invited_user_can_log_in_with_temp_password(client, make_auth_headers):
    owner_headers = make_auth_headers("CLI-INVITE-02", role="owner")
    invite_resp = client.post(
        "/api/v1/team/invite",
        json={"email": "logintest-invited@test.example", "role": "viewer"},
        headers=owner_headers,
    )
    assert invite_resp.status_code == 200
    temp_password = invite_resp.json()["temp_password"]

    login_resp = client.post("/api/v1/auth/login", json={
        "email": "logintest-invited@test.example", "password": temp_password,
    })
    assert login_resp.status_code == 200
    assert login_resp.json()["role"] == "viewer"


def test_member_cannot_invite(client, make_auth_headers):
    member_headers = make_auth_headers("CLI-INVITE-03", role="member")
    resp = client.post(
        "/api/v1/team/invite",
        json={"email": "shouldnt-exist@test.example", "role": "member"},
        headers=member_headers,
    )
    assert resp.status_code == 403


def test_viewer_cannot_invite(client, make_auth_headers):
    viewer_headers = make_auth_headers("CLI-INVITE-04", role="viewer")
    resp = client.post(
        "/api/v1/team/invite",
        json={"email": "shouldnt-exist-either@test.example", "role": "member"},
        headers=viewer_headers,
    )
    assert resp.status_code == 403


def test_invite_rejects_invalid_role(client, make_auth_headers):
    owner_headers = make_auth_headers("CLI-INVITE-05", role="owner")
    resp = client.post(
        "/api/v1/team/invite",
        json={"email": "bad-role@test.example", "role": "superadmin"},
        headers=owner_headers,
    )
    assert resp.status_code == 422


def test_any_role_can_list_team(client, make_auth_headers):
    make_auth_headers("CLI-LIST-01", role="owner")  # ensures the tenant exists
    viewer_headers = make_auth_headers("CLI-LIST-01", role="viewer")
    resp = client.get("/api/v1/team/users", headers=viewer_headers)
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()["users"]]
    assert "cli-list-01-owner@test.example" in emails
    assert "cli-list-01-viewer@test.example" in emails


def test_admin_can_change_teammate_role(client, make_auth_headers):
    owner_headers = make_auth_headers("CLI-ROLECHANGE-01", role="owner")
    member_headers = make_auth_headers("CLI-ROLECHANGE-01", role="member")
    me_resp = client.get("/api/v1/auth/me", headers=member_headers)
    member_id = me_resp.json()["user_id"]

    resp = client.patch(
        f"/api/v1/team/users/{member_id}/role",
        json={"role": "admin"},
        headers=owner_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_non_owner_cannot_change_roles(client, make_auth_headers):
    admin_headers = make_auth_headers("CLI-ROLECHANGE-02", role="admin")
    member_headers = make_auth_headers("CLI-ROLECHANGE-02", role="member")
    me_resp = client.get("/api/v1/auth/me", headers=member_headers)
    member_id = me_resp.json()["user_id"]

    resp = client.patch(
        f"/api/v1/team/users/{member_id}/role",
        json={"role": "admin"},
        headers=admin_headers,
    )
    assert resp.status_code == 403


def test_owner_cannot_demote_self(client, make_auth_headers):
    owner_headers = make_auth_headers("CLI-SELFDEMOTE-01", role="owner")
    me_resp = client.get("/api/v1/auth/me", headers=owner_headers)
    owner_id = me_resp.json()["user_id"]

    resp = client.patch(
        f"/api/v1/team/users/{owner_id}/role",
        json={"role": "member"},
        headers=owner_headers,
    )
    assert resp.status_code == 400


def test_owner_can_remove_teammate(client, make_auth_headers):
    owner_headers = make_auth_headers("CLI-REMOVE-01", role="owner")
    member_headers = make_auth_headers("CLI-REMOVE-01", role="member")
    me_resp = client.get("/api/v1/auth/me", headers=member_headers)
    member_id = me_resp.json()["user_id"]

    resp = client.delete(f"/api/v1/team/users/{member_id}", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.json()["removed"] is True

    # Removed user's OLD token is still cryptographically valid (JWTs
    # aren't revoked server-side on removal -- no session/blocklist
    # store exists yet) but every endpoint that looks the user back up
    # by id/tenant should now find nothing. Not asserted further here --
    # this is a real, disclosed limitation, not silently assumed fixed.


def test_owner_cannot_remove_self(client, make_auth_headers):
    owner_headers = make_auth_headers("CLI-SELFREMOVE-01", role="owner")
    me_resp = client.get("/api/v1/auth/me", headers=owner_headers)
    owner_id = me_resp.json()["user_id"]

    resp = client.delete(f"/api/v1/team/users/{owner_id}", headers=owner_headers)
    assert resp.status_code == 400


def test_remove_unknown_teammate_returns_404(client, make_auth_headers):
    owner_headers = make_auth_headers("CLI-REMOVE-02", role="owner")
    resp = client.delete("/api/v1/team/users/999999999", headers=owner_headers)
    assert resp.status_code == 404
