"""
INT-01: real coverage for backend/api_keys.py's REST management endpoints
(create/list/revoke a scoped MCP API key) -- owner/admin gating, the raw
key never appearing outside the create response, and cross-tenant
isolation on revoke. The MCP protocol layer itself (backend/mcp_server.py,
mounted at /mcp) is NOT exercised here -- TestClient's fake "testserver"
host fails the MCP SDK's own DNS-rebinding Host-header check, which needs
a real bound host:port to pass. See backend/tools/verify_mcp_server.py
for the real, end-to-end protocol-level verification (spins up a real
uvicorn process) that a checked-in pytest file can't do with TestClient.
"""
import re


def test_owner_can_create_list_and_revoke_a_key(client, make_auth_headers):
    owner_headers = make_auth_headers("CLI-MCP-01", role="owner")

    create_resp = client.post(
        "/api/v1/settings/api-keys",
        json={"label": "my mcp client"},
        headers=owner_headers,
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["api_key"].startswith("evta_live_")
    assert created["label"] == "my mcp client"
    assert re.match(r"^evta_live_.{10,}$", created["api_key"])
    key_id = created["key_id"]

    list_resp = client.get("/api/v1/settings/api-keys", headers=owner_headers)
    assert list_resp.status_code == 200
    rows = list_resp.json()["api_keys"]
    assert len(rows) == 1
    # The raw key and its hash must never appear in the list response --
    # only the short cleartext prefix survives past creation.
    assert "api_key" not in rows[0]
    assert "key_hash" not in rows[0]
    assert rows[0]["key_prefix"] == created["api_key"][:12]
    assert rows[0]["active"] is True

    revoke_resp = client.delete(f"/api/v1/settings/api-keys/{key_id}", headers=owner_headers)
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["revoked"] is True

    list_resp_2 = client.get("/api/v1/settings/api-keys", headers=owner_headers)
    assert list_resp_2.json()["api_keys"][0]["active"] is False


def test_admin_can_manage_keys(client, make_auth_headers):
    make_auth_headers("CLI-MCP-02", role="owner")  # tenant must exist first
    admin_headers = make_auth_headers("CLI-MCP-02", role="admin")
    resp = client.post("/api/v1/settings/api-keys", json={"label": "admin key"}, headers=admin_headers)
    assert resp.status_code == 200


def test_member_cannot_create_a_key(client, make_auth_headers):
    make_auth_headers("CLI-MCP-03", role="owner")
    member_headers = make_auth_headers("CLI-MCP-03", role="member")
    resp = client.post("/api/v1/settings/api-keys", json={"label": "nope"}, headers=member_headers)
    assert resp.status_code == 403


def test_viewer_cannot_list_or_revoke_keys(client, make_auth_headers):
    owner_headers = make_auth_headers("CLI-MCP-04", role="owner")
    created = client.post(
        "/api/v1/settings/api-keys", json={"label": "owner key"}, headers=owner_headers,
    ).json()
    viewer_headers = make_auth_headers("CLI-MCP-04", role="viewer")

    assert client.get("/api/v1/settings/api-keys", headers=viewer_headers).status_code == 403
    assert client.delete(
        f"/api/v1/settings/api-keys/{created['key_id']}", headers=viewer_headers
    ).status_code == 403


def test_revoke_is_scoped_to_the_owning_tenant(client, make_auth_headers):
    """
    A cross-tenant revoke must fail closed (404, "not owned by this
    tenant"), never silently succeed against another tenant's key --
    db_manager.revoke_api_key's own WHERE client_id = ? AND key_id = ?
    guard is what this exercises at the HTTP layer.
    """
    tenant_a_headers = make_auth_headers("CLI-MCP-05-A", role="owner")
    tenant_b_headers = make_auth_headers("CLI-MCP-05-B", role="owner")

    created = client.post(
        "/api/v1/settings/api-keys", json={"label": "tenant a key"}, headers=tenant_a_headers,
    ).json()

    cross_tenant_resp = client.delete(
        f"/api/v1/settings/api-keys/{created['key_id']}", headers=tenant_b_headers,
    )
    assert cross_tenant_resp.status_code == 404

    # Tenant A's own revoke of the SAME key still works afterward --
    # confirms the 404 above was really "not yours", not "already gone".
    real_revoke_resp = client.delete(
        f"/api/v1/settings/api-keys/{created['key_id']}", headers=tenant_a_headers,
    )
    assert real_revoke_resp.status_code == 200


def test_revoking_an_already_revoked_key_404s(client, make_auth_headers):
    owner_headers = make_auth_headers("CLI-MCP-06", role="owner")
    created = client.post(
        "/api/v1/settings/api-keys", json={"label": "double revoke"}, headers=owner_headers,
    ).json()
    key_id = created["key_id"]
    assert client.delete(f"/api/v1/settings/api-keys/{key_id}", headers=owner_headers).status_code == 200
    assert client.delete(f"/api/v1/settings/api-keys/{key_id}", headers=owner_headers).status_code == 404
