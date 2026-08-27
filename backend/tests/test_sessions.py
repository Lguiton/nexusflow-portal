"""
AUTH-06: real coverage for session/device management -- GET
/api/v1/auth/sessions, DELETE /api/v1/auth/sessions/{session_id}, and
POST /api/v1/auth/sessions/revoke-all (backend/accounts.py), backed by
the device_label/session_started_at columns AUTH-06 added to the
refresh_tokens table (backend/db_manager.py). No mocking -- these hit the
real endpoints against a real isolated DuckDB.
"""


def _signup(client, seed: str, user_agent: str = None):
    email = f"{seed}@test.example"
    # None -> no override (TestClient's own default "testclient" UA is
    # sent); "" or a real string -> explicitly set that header. Using
    # `is not None` here (not truthiness) is what lets the empty-UA test
    # below actually force a genuinely empty User-Agent header instead of
    # silently falling back to TestClient's default.
    headers = {"User-Agent": user_agent} if user_agent is not None else {}
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": f"Sessions Test {seed}",
            "email": email,
            "password": "correct-horse-battery-staple",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return email, resp.json()


CHROME_WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
SAFARI_IOS_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def test_a_fresh_login_shows_up_in_the_sessions_list_with_a_derived_device_label(client):
    email, signup_body = _signup(client, "sessions-list-01", user_agent=CHROME_WINDOWS_UA)
    headers = {"Authorization": f"Bearer {signup_body['access_token']}"}

    resp = client.get("/api/v1/auth/sessions", headers=headers)
    assert resp.status_code == 200, resp.text
    sessions = resp.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["device_label"] == "Chrome on Windows"
    assert sessions[0]["session_started_at"] is not None
    assert sessions[0]["expires_at"] is not None
    assert "token_hash" not in sessions[0] and "refresh_token" not in sessions[0]


def test_device_label_is_derived_per_platform_and_browser(client):
    _, signup_body = _signup(client, "sessions-ua-01", user_agent=SAFARI_IOS_UA)
    headers = {"Authorization": f"Bearer {signup_body['access_token']}"}
    sessions = client.get("/api/v1/auth/sessions", headers=headers).json()["sessions"]
    assert sessions[0]["device_label"] == "Safari on iOS"


def test_refreshing_keeps_the_same_device_label_and_session_start_time(client):
    """
    The core AUTH-06 property: a rotation must NOT look like a brand-new
    device/session in the list -- device_label and session_started_at
    should be carried forward unchanged across the whole rotation chain.
    """
    _, signup_body = _signup(client, "sessions-rotate-01", user_agent=CHROME_WINDOWS_UA)
    old_refresh = signup_body["refresh_token"]
    access_headers = {"Authorization": f"Bearer {signup_body['access_token']}"}

    before = client.get("/api/v1/auth/sessions", headers=access_headers).json()["sessions"]
    assert len(before) == 1
    started_before = before[0]["session_started_at"]

    rotate = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert rotate.status_code == 200, rotate.text
    new_access_headers = {"Authorization": f"Bearer {rotate.json()['access_token']}"}

    after = client.get("/api/v1/auth/sessions", headers=new_access_headers).json()["sessions"]
    assert len(after) == 1
    assert after[0]["device_label"] == "Chrome on Windows"
    assert after[0]["session_started_at"] == started_before


def test_listing_sessions_never_returns_another_users_sessions(client):
    _, body_a = _signup(client, "sessions-isolation-a", user_agent=CHROME_WINDOWS_UA)
    _, body_b = _signup(client, "sessions-isolation-b", user_agent=SAFARI_IOS_UA)

    headers_a = {"Authorization": f"Bearer {body_a['access_token']}"}
    sessions_a = client.get("/api/v1/auth/sessions", headers=headers_a).json()["sessions"]
    assert len(sessions_a) == 1
    assert sessions_a[0]["device_label"] == "Chrome on Windows"


def test_two_logins_from_the_same_user_show_as_two_separate_sessions(client):
    email, first = _signup(client, "sessions-multi-01", user_agent=CHROME_WINDOWS_UA)
    second = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery-staple"},
        headers={"User-Agent": SAFARI_IOS_UA},
    )
    assert second.status_code == 200, second.text

    headers = {"Authorization": f"Bearer {first['access_token']}"}
    sessions = client.get("/api/v1/auth/sessions", headers=headers).json()["sessions"]
    assert len(sessions) == 2
    labels = {s["device_label"] for s in sessions}
    assert labels == {"Chrome on Windows", "Safari on iOS"}


def test_deleting_a_specific_session_revokes_only_that_ones_refresh_token(client):
    email, first = _signup(client, "sessions-delete-01", user_agent=CHROME_WINDOWS_UA)
    second = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery-staple"},
        headers={"User-Agent": SAFARI_IOS_UA},
    )
    second_body = second.json()

    headers = {"Authorization": f"Bearer {first['access_token']}"}
    sessions = client.get("/api/v1/auth/sessions", headers=headers).json()["sessions"]
    ios_session = next(s for s in sessions if s["device_label"] == "Safari on iOS")

    del_resp = client.delete(f"/api/v1/auth/sessions/{ios_session['session_id']}", headers=headers)
    assert del_resp.status_code == 200, del_resp.text
    assert del_resp.json() == {"session_id": ios_session["session_id"], "revoked": True}

    # The revoked session's refresh token is dead...
    dead_refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": second_body["refresh_token"]})
    assert dead_refresh.status_code == 401, dead_refresh.text

    # ...but the OTHER session (the caller's own) is completely untouched.
    still_alive = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert still_alive.status_code == 200, still_alive.text


def test_deleting_a_session_that_does_not_belong_to_the_caller_404s(client):
    _, body_a = _signup(client, "sessions-scope-a", user_agent=CHROME_WINDOWS_UA)
    _, body_b = _signup(client, "sessions-scope-b", user_agent=SAFARI_IOS_UA)

    headers_b = {"Authorization": f"Bearer {body_b['access_token']}"}
    sessions_b = client.get("/api/v1/auth/sessions", headers=headers_b).json()["sessions"]
    b_session_id = sessions_b[0]["session_id"]

    headers_a = {"Authorization": f"Bearer {body_a['access_token']}"}
    resp = client.delete(f"/api/v1/auth/sessions/{b_session_id}", headers=headers_a)
    assert resp.status_code == 404, resp.text

    # And B's session is still perfectly alive -- A's attempt had no effect.
    still_alive = client.post("/api/v1/auth/refresh", json={"refresh_token": body_b["refresh_token"]})
    assert still_alive.status_code == 200, still_alive.text


def test_deleting_a_made_up_session_id_404s(client):
    _, body = _signup(client, "sessions-fake-id-01")
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    resp = client.delete("/api/v1/auth/sessions/999999999", headers=headers)
    assert resp.status_code == 404, resp.text


def test_deleting_an_already_revoked_session_404s_on_the_second_try(client):
    _, body = _signup(client, "sessions-double-delete-01")
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    session_id = client.get("/api/v1/auth/sessions", headers=headers).json()["sessions"][0]["session_id"]

    first = client.delete(f"/api/v1/auth/sessions/{session_id}", headers=headers)
    assert first.status_code == 200, first.text

    second = client.delete(f"/api/v1/auth/sessions/{session_id}", headers=headers)
    assert second.status_code == 404, second.text


def test_revoke_all_kills_every_session_including_the_current_one(client):
    email, first = _signup(client, "sessions-revoke-all-01", user_agent=CHROME_WINDOWS_UA)
    second = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery-staple"},
        headers={"User-Agent": SAFARI_IOS_UA},
    )
    second_body = second.json()

    headers = {"Authorization": f"Bearer {first['access_token']}"}
    resp = client.post("/api/v1/auth/sessions/revoke-all", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}

    dead_1 = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert dead_1.status_code == 401, dead_1.text
    dead_2 = client.post("/api/v1/auth/refresh", json={"refresh_token": second_body["refresh_token"]})
    assert dead_2.status_code == 401, dead_2.text


def test_a_revoked_session_no_longer_appears_in_the_list(client):
    email, first = _signup(client, "sessions-list-after-delete-01", user_agent=CHROME_WINDOWS_UA)
    second = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery-staple"},
        headers={"User-Agent": SAFARI_IOS_UA},
    )
    headers = {"Authorization": f"Bearer {first['access_token']}"}

    sessions = client.get("/api/v1/auth/sessions", headers=headers).json()["sessions"]
    assert len(sessions) == 2
    ios_session = next(s for s in sessions if s["device_label"] == "Safari on iOS")
    client.delete(f"/api/v1/auth/sessions/{ios_session['session_id']}", headers=headers)

    remaining = client.get("/api/v1/auth/sessions", headers=headers).json()["sessions"]
    assert len(remaining) == 1
    assert remaining[0]["device_label"] == "Chrome on Windows"


def test_an_unrecognized_user_agent_falls_back_to_a_truncated_raw_string(client):
    weird_ua = "SomeCustomApiClient/1.0 (internal-tooling)"
    _, body = _signup(client, "sessions-weird-ua-01", user_agent=weird_ua)
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    sessions = client.get("/api/v1/auth/sessions", headers=headers).json()["sessions"]
    assert sessions[0]["device_label"] == weird_ua


def test_an_empty_user_agent_stores_a_null_device_label_without_erroring(client):
    # The test client itself always sends a real (if useless -- "testclient")
    # User-Agent when none is given, so an actually-empty header has to be
    # forced explicitly to exercise the "no UA at all" branch of
    # _derive_device_label.
    _, body = _signup(client, "sessions-no-ua-01", user_agent="")
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    resp = client.get("/api/v1/auth/sessions", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["sessions"][0]["device_label"] is None


def test_sessions_endpoints_require_a_real_access_token(client):
    assert client.get("/api/v1/auth/sessions").status_code in (401, 403)
    assert client.delete("/api/v1/auth/sessions/1").status_code in (401, 403)
    assert client.post("/api/v1/auth/sessions/revoke-all").status_code in (401, 403)
