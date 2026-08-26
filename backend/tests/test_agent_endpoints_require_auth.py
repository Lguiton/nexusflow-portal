"""
Auth-gate coverage for every endpoint whose real handler body calls out to
an OpenAI-backed agent (cognitive search, CFO briefing, forecast, BI
summary, schema audit, SaaS strategy, chart suite, stakeholder report).

This suite deliberately does NOT make real OpenAI calls (no live API
assertions on agent output) -- that would cost real money per test run,
be non-deterministic, and isn't needed to verify the thing actually worth
pinning down here: the auth Depends() runs BEFORE the handler body reaches
the agent call, so a request with no/invalid token is rejected with 401
and never reaches OpenAI at all. If real end-to-end agent-output testing
is wanted later, it belongs in a separate, explicitly-opt-in suite (e.g.
gated behind an OPENAI_API_KEY / EIVANTA_LIVE_LLM_TESTS env check) --
not bundled into the suite that runs on every `pytest` invocation.
"""
import pytest


@pytest.mark.parametrize("path,body", [
    ("/api/search", {"query": "what is my revenue"}),
    ("/api/v1/finance/cfo-briefing", None),
    ("/api/v1/predictive/forecast", None),
    ("/api/v1/data/schema-audit", None),
    ("/api/v1/bi/summary", {}),
    ("/api/v1/saas/strategy", None),
    ("/api/v1/bi/chart-suite", None),
    ("/api/v1/reports/stakeholder", None),
])
def test_agent_backed_endpoints_reject_missing_auth(client, path, body):
    kwargs = {"json": body} if body is not None else {}
    resp = client.post(path, **kwargs)
    assert resp.status_code == 401, f"POST {path} should require auth before ever reaching the agent, got {resp.status_code}"


def test_search_requires_nonempty_query(client, auth_headers):
    # Pydantic validation (min_length=1) fires before auth's Depends() body
    # even runs the agent call -- a blank query should be a 422, not a 401
    # or a 502 from a doomed agent call.
    resp = client.post("/api/search", json={"query": ""}, headers=auth_headers)
    assert resp.status_code == 422
