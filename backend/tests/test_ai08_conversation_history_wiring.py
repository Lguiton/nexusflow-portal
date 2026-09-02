"""
AI-08: multi-turn conversational memory, extended to the 7 agent functions
that weren't wired to it yet (Track 4 originally wired only BI Engineer --
see orchestrator.execute_bi_engineer's own comment history). This suite
proves the mechanical follow-up actually landed, in two layers:

1. Orchestrator wiring: each of the 8 execute_* graph nodes in
   orchestrator.py actually passes state["conversation_history"] through to
   its underlying agent function call -- proven directly and cheaply (no
   DB, no LLM) by monkeypatching each agent module's public function to a
   capturing stub and calling the node function with a minimal SwarmState.

2. Per-agent prompt threading: for the 7 agent functions that build a real
   LLM narrative prompt (virtual_cfo, data_engineer, predictive_forecaster,
   saas_strategist, report_generator, bi_visualization_architect,
   external_telemetry_scout), conversation_history actually reaches the
   system prompt text sent to the model -- proven with a stubbed OpenAI
   client (same discipline as test_orchestrator_integration.py's Layer 3
   and test_query_audit.py -- no live API key needed) against real seeded
   ledger data, so each agent's own NO_DATA/empty-state guard is passed for
   real rather than short-circuiting before ever reaching the prompt.

BI Engineer itself is NOT re-tested here -- its conversation_history wiring
predates this change (Track 4) and belongs to bi_engineer.py's own test
surface; this suite only proves it's still correctly dispatched by the
orchestrator node (Layer 1), for symmetry with the other 7.
"""
import json

import pytest


# ---------------------------------------------------------------------------
# Shared capturing OpenAI stub -- same shape as test_orchestrator_integration
# .py's _StubOpenAIClient, extended to record every call's kwargs.
# ---------------------------------------------------------------------------

class _StubMessage:
    def __init__(self, content):
        self.content = content


class _StubChoice:
    def __init__(self, content):
        self.message = _StubMessage(content)


class _StubCompletion:
    def __init__(self, content):
        self.choices = [_StubChoice(content)]
        self.usage = None


class _CapturingChatCompletions:
    def __init__(self, content):
        self._content = content
        self.calls = []

    def create(self, *args, **kwargs):
        self.calls.append(kwargs)
        return _StubCompletion(self._content)


class _StubChat:
    def __init__(self, chat_completions):
        self.completions = chat_completions


class _StubOpenAIClient:
    def __init__(self, content):
        self._completions = _CapturingChatCompletions(content)
        self.chat = _StubChat(self._completions)


def _system_prompt_from(stub_client):
    assert len(stub_client._completions.calls) == 1
    messages = stub_client._completions.calls[0]["messages"]
    return next(m["content"] for m in messages if m["role"] == "system")


_SENTINEL_HISTORY = [
    {"role": "user", "content": "what happened last quarter?"},
    {"role": "assistant", "content": "Revenue grew 8% quarter over quarter."},
]


def _base_state(**overrides):
    state = {
        "client_id": "CLI-AI08-TEST",
        "query": "follow-up question",
        "active_agent": "router",
        "results": {},
        "status": "PENDING",
        "errors": [],
        "connection_key": None,
        "sample_payload": None,
        "session_id": None,
        "conversation_history": _SENTINEL_HISTORY,
        "user_id": None,
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Layer 1: orchestrator wiring -- each execute_* node passes
# state["conversation_history"] through to its agent function call.
# ---------------------------------------------------------------------------

def test_execute_virtual_cfo_passes_conversation_history(monkeypatch):
    from backend.agents import orchestrator, virtual_cfo

    captured = {}
    monkeypatch.setattr(
        virtual_cfo, "generate_cfo_briefing",
        lambda client_id, conversation_history=None: captured.setdefault("history", conversation_history) or {"status": "NO_DATA"},
    )
    orchestrator.execute_virtual_cfo(_base_state())
    assert captured["history"] == _SENTINEL_HISTORY


def test_execute_data_engineer_passes_conversation_history(monkeypatch):
    from backend.agents import orchestrator, data_engineer

    captured = {}
    monkeypatch.setattr(
        data_engineer, "analyze_schema_quality",
        lambda client_id, conversation_history=None: captured.setdefault("history", conversation_history) or {"status": "NO_DATA"},
    )
    orchestrator.execute_data_engineer(_base_state())
    assert captured["history"] == _SENTINEL_HISTORY


def test_execute_bi_engineer_still_passes_conversation_history(monkeypatch):
    """Symmetry check, not a re-test of Track 4's original wiring: proves
    the AI-08 changes to this node's surrounding comment/code didn't
    regress the pre-existing history threading."""
    from backend.agents import orchestrator, bi_engineer

    captured = {}
    monkeypatch.setattr(
        bi_engineer, "generate_bi_summary",
        lambda client_id, query, conversation_history=None, user_id=None: (
            captured.setdefault("history", conversation_history) or {"status": "NO_DATA"}
        ),
    )
    orchestrator.execute_bi_engineer(_base_state())
    assert captured["history"] == _SENTINEL_HISTORY


def test_execute_predictive_forecaster_passes_conversation_history(monkeypatch):
    from backend.agents import orchestrator, predictive_forecaster

    captured = {}
    monkeypatch.setattr(
        predictive_forecaster, "generate_forecast",
        lambda client_id, conversation_history=None: captured.setdefault("history", conversation_history) or {"status": "NO_DATA"},
    )
    orchestrator.execute_predictive_forecaster(_base_state())
    assert captured["history"] == _SENTINEL_HISTORY


def test_execute_saas_strategist_passes_conversation_history(monkeypatch):
    from backend.agents import orchestrator, saas_strategist

    captured = {}
    monkeypatch.setattr(
        saas_strategist, "generate_strategy",
        lambda client_id, conversation_history=None: captured.setdefault("history", conversation_history) or {"status": "NO_DATA"},
    )
    orchestrator.execute_saas_strategist(_base_state())
    assert captured["history"] == _SENTINEL_HISTORY


def test_execute_report_generator_passes_conversation_history(monkeypatch):
    from backend.agents import orchestrator, report_generator

    captured = {}
    monkeypatch.setattr(
        report_generator, "generate_stakeholder_report",
        lambda client_id, conversation_history=None: captured.setdefault("history", conversation_history) or {"status": "NO_DATA"},
    )
    orchestrator.execute_report_generator(_base_state())
    assert captured["history"] == _SENTINEL_HISTORY


def test_execute_bi_visualization_architect_passes_conversation_history(monkeypatch):
    from backend.agents import orchestrator, bi_visualization_architect

    captured = {}
    monkeypatch.setattr(
        bi_visualization_architect, "execute_task",
        lambda client_id, query, conversation_history=None: captured.setdefault("history", conversation_history) or {"status": "NO_DATA"},
    )
    orchestrator.execute_bi_visualization_architect(_base_state())
    assert captured["history"] == _SENTINEL_HISTORY


def test_execute_external_telemetry_scout_passes_conversation_history(monkeypatch):
    from backend.agents import orchestrator, external_telemetry_scout

    captured = {}
    monkeypatch.setattr(
        external_telemetry_scout, "execute_task",
        lambda client_id, query, sample_payload=None, conversation_history=None: (
            captured.setdefault("history", conversation_history) or {"status": "ERROR", "insights": []}
        ),
    )
    orchestrator.execute_external_telemetry_scout(_base_state(sample_payload={"a": 1}))
    assert captured["history"] == _SENTINEL_HISTORY


def test_missing_conversation_history_defaults_to_empty_list_not_none(monkeypatch):
    """state.get("conversation_history") or [] -- a state dict predating
    AI-08 (missing the key entirely) must degrade to [], never crash or
    pass None through to a function whose helper does `if not
    conversation_history: return ""` (which handles both fine, but the
    orchestrator's own `or []` normalization is worth pinning directly)."""
    from backend.agents import orchestrator, virtual_cfo

    captured = {}
    monkeypatch.setattr(
        virtual_cfo, "generate_cfo_briefing",
        lambda client_id, conversation_history=None: captured.setdefault("history", conversation_history) or {"status": "NO_DATA"},
    )
    state = _base_state()
    del state["conversation_history"]
    orchestrator.execute_virtual_cfo(state)
    assert captured["history"] == []


# ---------------------------------------------------------------------------
# Layer 2: per-agent proof that conversation_history reaches the real LLM
# system prompt, against real seeded ledger data (so each agent's own
# NO_DATA/empty-state guard is passed for real).
# ---------------------------------------------------------------------------

def _seed_four_months(isolated_db, tmp_path, tenant):
    """4 distinct months of revenue -- satisfies every DB-backed narrative
    agent's own minimum-data gate in this suite, including
    predictive_forecaster's MIN_PERIODS_FOR_FORECAST=4 (the strictest one)."""
    import asyncio

    csv_path = tmp_path / "ai08_seed.csv"
    csv_path.write_text(
        "date,category,amount,description\n"
        "2026-01-15,Revenue,4000,seed\n"
        "2026-02-15,Revenue,4200,seed\n"
        "2026-03-15,Revenue,4400,seed\n"
        "2026-04-15,Revenue,4600,seed\n",
        encoding="utf-8",
    )
    asyncio.run(isolated_db.ingest_csv_to_db(str(csv_path), tenant, "ai08_seed.csv"))


def test_virtual_cfo_history_reaches_the_system_prompt(isolated_db, tmp_path, monkeypatch):
    from backend.agents import virtual_cfo

    tenant = "CLI-AI08-CFO"
    _seed_four_months(isolated_db, tmp_path, tenant)
    stub_client = _StubOpenAIClient(json.dumps({
        "metrics": {"gross_margin": 90.0, "burn_rate": 0.0, "cash_runway_months": 99.9},
        "insights": ["a", "b", "c"],
    }))
    monkeypatch.setattr(virtual_cfo, "get_openai_client_for_tenant_sync",
                         lambda *a, **kw: stub_client)

    virtual_cfo.generate_cfo_briefing(tenant, conversation_history=_SENTINEL_HISTORY)

    prompt = _system_prompt_from(stub_client)
    assert "what happened last quarter?" in prompt
    assert "Revenue grew 8% quarter over quarter." in prompt


def test_data_engineer_history_reaches_the_system_prompt(isolated_db, tmp_path, monkeypatch):
    from backend.agents import data_engineer

    tenant = "CLI-AI08-DE"
    _seed_four_months(isolated_db, tmp_path, tenant)
    stub_client = _StubOpenAIClient(json.dumps({
        "agent": "Systems Analyst Agent #02", "status": "OPTIMIZED", "recommendations": ["a", "b", "c"],
    }))
    monkeypatch.setattr(data_engineer, "get_openai_client_for_tenant_sync",
                         lambda *a, **kw: stub_client)

    data_engineer.analyze_schema_quality(tenant, conversation_history=_SENTINEL_HISTORY)

    prompt = _system_prompt_from(stub_client)
    assert "what happened last quarter?" in prompt


def test_predictive_forecaster_history_reaches_the_system_prompt(isolated_db, tmp_path, monkeypatch):
    from backend.agents import predictive_forecaster

    tenant = "CLI-AI08-PF"
    _seed_four_months(isolated_db, tmp_path, tenant)
    stub_client = _StubOpenAIClient(json.dumps({
        "agent": "Predictive Forecaster Agent #07", "status": "FORECASTED", "projections": ["a", "b", "c"],
    }))
    monkeypatch.setattr(predictive_forecaster, "get_openai_client_for_tenant_sync",
                         lambda *a, **kw: stub_client)

    predictive_forecaster.generate_forecast(tenant, conversation_history=_SENTINEL_HISTORY)

    prompt = _system_prompt_from(stub_client)
    assert "what happened last quarter?" in prompt


def test_saas_strategist_history_reaches_the_system_prompt(isolated_db, tmp_path, monkeypatch):
    from backend.agents import saas_strategist

    tenant = "CLI-AI08-SS"
    _seed_four_months(isolated_db, tmp_path, tenant)
    stub_client = _StubOpenAIClient(json.dumps({
        "agent": "SaaS Strategist Agent #10", "status": "OPTIMIZED", "strategies": ["a", "b", "c"],
    }))
    monkeypatch.setattr(saas_strategist, "get_openai_client_for_tenant_sync",
                         lambda *a, **kw: stub_client)

    saas_strategist.generate_strategy(tenant, conversation_history=_SENTINEL_HISTORY)

    prompt = _system_prompt_from(stub_client)
    assert "what happened last quarter?" in prompt


def test_report_generator_history_reaches_the_system_prompt(isolated_db, tmp_path, monkeypatch):
    from backend.agents import report_generator

    tenant = "CLI-AI08-RG"
    _seed_four_months(isolated_db, tmp_path, tenant)
    stub_client = _StubOpenAIClient(json.dumps({
        "agent": "Report Generator Agent #06", "status": "GENERATED",
        "summary_metrics": {"total_revenue": 1, "total_expenses": 0, "net_income": 1, "records_audited": 4},
        "executive_sections": [{"title": "t", "summary": "s"}],
    }))
    monkeypatch.setattr(report_generator, "get_openai_client_for_tenant_sync",
                         lambda *a, **kw: stub_client)

    report_generator.generate_stakeholder_report(tenant, conversation_history=_SENTINEL_HISTORY)

    prompt = _system_prompt_from(stub_client)
    assert "what happened last quarter?" in prompt


def test_bi_visualization_architect_history_reaches_the_system_prompt(isolated_db, tmp_path, monkeypatch):
    from backend.agents import bi_visualization_architect

    tenant = "CLI-AI08-VIZ"
    _seed_four_months(isolated_db, tmp_path, tenant)
    stub_client = _StubOpenAIClient(json.dumps({"insights": ["a"]}))
    monkeypatch.setattr(bi_visualization_architect, "get_openai_client_for_tenant_sync",
                         lambda *a, **kw: stub_client)

    bi_visualization_architect.execute_task(tenant, "show me a chart", conversation_history=_SENTINEL_HISTORY)

    prompt = _system_prompt_from(stub_client)
    assert "what happened last quarter?" in prompt


def test_external_telemetry_scout_history_reaches_the_system_prompt(monkeypatch):
    # No DB seeding needed -- this agent's only precondition is a valid
    # sample_payload, proven separately by its own existing code path.
    from backend.agents import external_telemetry_scout

    stub_client = _StubOpenAIClient(json.dumps({"insights": ["a"]}))
    monkeypatch.setattr(external_telemetry_scout, "get_openai_client_for_tenant_sync",
                         lambda *a, **kw: stub_client)

    external_telemetry_scout.execute_task(
        "CLI-AI08-SCOUT", "map this payload", sample_payload={"user_id": 1, "event": "signup"},
        conversation_history=_SENTINEL_HISTORY,
    )

    prompt = _system_prompt_from(stub_client)
    assert "what happened last quarter?" in prompt


@pytest.mark.parametrize("agent_module_name,func_name,call_kwargs", [
    ("virtual_cfo", "generate_cfo_briefing", {}),
    ("data_engineer", "analyze_schema_quality", {}),
    ("predictive_forecaster", "generate_forecast", {}),
    ("saas_strategist", "generate_strategy", {}),
    ("report_generator", "generate_stakeholder_report", {}),
])
def test_omitted_history_keeps_todays_exact_behavior_no_history_block(
    isolated_db, tmp_path, monkeypatch, agent_module_name, func_name, call_kwargs,
):
    """Additive-only proof: a caller that doesn't pass conversation_history
    at all must get the exact same (empty) history block as before AI-08 --
    no stray placeholder text, no crash from a missing argument."""
    import importlib

    tenant = f"CLI-AI08-OMIT-{agent_module_name}"
    _seed_four_months(isolated_db, tmp_path, tenant)
    module = importlib.import_module(f"backend.agents.{agent_module_name}")

    canned = {
        "virtual_cfo": json.dumps({"metrics": {"gross_margin": 1, "burn_rate": 1, "cash_runway_months": 1}, "insights": ["a", "b", "c"]}),
        "data_engineer": json.dumps({"agent": "x", "status": "OPTIMIZED", "recommendations": ["a", "b", "c"]}),
        "predictive_forecaster": json.dumps({"agent": "x", "status": "FORECASTED", "projections": ["a", "b", "c"]}),
        "saas_strategist": json.dumps({"agent": "x", "status": "OPTIMIZED", "strategies": ["a", "b", "c"]}),
        "report_generator": json.dumps({
            "agent": "x", "status": "GENERATED",
            "summary_metrics": {"total_revenue": 1, "total_expenses": 0, "net_income": 1, "records_audited": 4},
            "executive_sections": [{"title": "t", "summary": "s"}],
        }),
    }[agent_module_name]

    stub_client = _StubOpenAIClient(canned)
    monkeypatch.setattr(module, "get_openai_client_for_tenant_sync", lambda *a, **kw: stub_client)

    func = getattr(module, func_name)
    func(tenant, **call_kwargs)  # conversation_history omitted entirely

    prompt = _system_prompt_from(stub_client)
    assert "Recent conversation in this session" not in prompt
