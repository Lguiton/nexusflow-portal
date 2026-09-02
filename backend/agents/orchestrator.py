import logging
import asyncio
import time
from typing import Dict, Any, List, TypedDict, Optional
from langgraph.graph import StateGraph, END
try:
    from backend.db_manager import (
        log_task_execution, log_conversation_turn, get_conversation_history, log_lineage_entry_sync,
    )
except ImportError:
    from db_manager import (
        log_task_execution, log_conversation_turn, get_conversation_history, log_lineage_entry_sync,
    )
try:
    from backend.websocket_manager import manager
except ImportError:
    from websocket_manager import manager
logger = logging.getLogger("eivanta.orchestrator")
class SwarmState(TypedDict):
    client_id: str
    query: str
    active_agent: str
    results: Dict[str, Any]
    status: str
    errors: List[str]
    connection_key: Optional[str]
    sample_payload: Optional[Any]
    session_id: Optional[str]
    conversation_history: List[Dict[str, Any]]
    user_id: Optional[int]
def _in_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False
def _sync_log_task(agent_name: str, status: str, exec_time: float):
    if _in_running_loop():
        logger.warning(f"Telemetry skipped for {agent_name}: already inside a running event loop.")
        return
    try:
        asyncio.run(log_task_execution(agent_name, status, exec_time))
    except Exception as e:
        logger.error(f"Telemetry sync failed for {agent_name}: {e}")
def _sync_broadcast(connection_key: Optional[str], agent: str, status: str, payload: dict):
    if not connection_key:
        return
    if _in_running_loop():
        logger.warning(f"Swarm broadcast skipped for {connection_key}: already inside a running event loop.")
        return
    try:
        asyncio.run(manager.broadcast_agent_step(connection_key, agent, status, payload))
    except Exception as e:
        logger.error(f"Swarm broadcast failed for {connection_key}: {e}")
# Track 4: multi-turn conversational memory. Mirrors the exact
# _in_running_loop()-guarded asyncio.run() pattern already used by
# _sync_log_task/_sync_broadcast above -- route_query() (which calls these)
# is itself invoked via asyncio.to_thread() from main.py, so it never runs
# inside an already-active event loop; these fail safe (return empty /
# no-op) rather than raise if that assumption is ever violated.
def _sync_get_history(client_id: str, session_id: Optional[str], limit: int = 6) -> List[Dict[str, Any]]:
    if not session_id:
        return []
    if _in_running_loop():
        logger.warning(f"Conversation history fetch skipped for {client_id}: already inside a running event loop.")
        return []
    try:
        return asyncio.run(get_conversation_history(client_id, session_id, limit))
    except Exception as e:
        logger.error(f"Conversation history fetch failed for {client_id}: {e}")
        return []
def _sync_log_turn(client_id: str, session_id: Optional[str], role: str, content: str, agent_name: Optional[str] = None):
    if not session_id:
        return
    if _in_running_loop():
        logger.warning(f"Conversation turn logging skipped for {client_id}: already inside a running event loop.")
        return
    try:
        asyncio.run(log_conversation_turn(client_id, session_id, role, content, agent_name))
    except Exception as e:
        logger.error(f"Conversation turn logging failed for {client_id}: {e}")
def execute_virtual_cfo(state: SwarmState) -> SwarmState:
    start_time = time.time()
    connection_key = state.get("connection_key")
    _sync_broadcast(connection_key, "virtual_cfo", "RUNNING", {"message": "Generating CFO briefing."})
    try:
        try:
            from backend.agents.virtual_cfo import generate_cfo_briefing
        except ImportError:
            from agents.virtual_cfo import generate_cfo_briefing
        # AI-08: mechanical follow-up to Track 4's original BI Engineer
        # wiring -- see execute_bi_engineer's comment below for the history.
        state["results"]["virtual_cfo"] = generate_cfo_briefing(
            state["client_id"], conversation_history=state.get("conversation_history") or [],
        )
        state["status"] = "COMPLETE"
        exec_time = time.time() - start_time
        _sync_log_task("virtual_cfo", "COMPLETE", exec_time)
        _sync_broadcast(connection_key, "virtual_cfo", "COMPLETE", {"message": "CFO briefing complete."})
    except Exception as e:
        exec_time = time.time() - start_time
        _sync_log_task("virtual_cfo", "ERROR", exec_time)
        state["status"] = "ERROR"
        state["errors"].append(str(e))
        _sync_broadcast(connection_key, "virtual_cfo", "ERROR", {"message": str(e)})
    return state
def execute_data_engineer(state: SwarmState) -> SwarmState:
    start_time = time.time()
    connection_key = state.get("connection_key")
    _sync_broadcast(connection_key, "data_engineer", "RUNNING", {"message": "Running schema audit."})
    try:
        try:
            from backend.agents.data_engineer import analyze_schema_quality
        except ImportError:
            from agents.data_engineer import analyze_schema_quality
        # AI-08: mechanical follow-up -- see execute_bi_engineer's comment below.
        state["results"]["data_engineer"] = analyze_schema_quality(
            state["client_id"], conversation_history=state.get("conversation_history") or [],
        )
        state["status"] = "COMPLETE"
        exec_time = time.time() - start_time
        _sync_log_task("data_engineer", "COMPLETE", exec_time)
        _sync_broadcast(connection_key, "data_engineer", "COMPLETE", {"message": "Schema audit complete."})
    except Exception as e:
        exec_time = time.time() - start_time
        _sync_log_task("data_engineer", "ERROR", exec_time)
        state["status"] = "ERROR"
        state["errors"].append(str(e))
        _sync_broadcast(connection_key, "data_engineer", "ERROR", {"message": str(e)})
    return state
def execute_bi_engineer(state: SwarmState) -> SwarmState:
    start_time = time.time()
    connection_key = state.get("connection_key")
    _sync_broadcast(connection_key, "bi_engineer", "RUNNING", {"message": "Generating BI summary."})
    try:
        try:
            from backend.agents.bi_engineer import generate_bi_summary
        except ImportError:
            from agents.bi_engineer import generate_bi_summary
        # Track 4: the first agent wired to real conversation history -- BI
        # Engineer folds in the ad hoc Q&A duties (Data Analyst #04), making
        # it the most naturally conversational agent (follow-up questions
        # like "what about last month?" only resolve with real prior
        # context). AI-08 (27 Aug 2026): the other 7 agent functions are now
        # wired to the same history too -- mechanical follow-up, same
        # partial-rollout-then-complete pattern BYOK's rollout used
        # (ops_shield.py first, rest mechanical follow-up).
        state["results"]["bi_engineer"] = generate_bi_summary(
            state["client_id"], state["query"],
            conversation_history=state.get("conversation_history") or [],
            user_id=state.get("user_id"),
        )
        state["status"] = "COMPLETE"
        exec_time = time.time() - start_time
        _sync_log_task("bi_engineer", "COMPLETE", exec_time)
        _sync_broadcast(connection_key, "bi_engineer", "COMPLETE", {"message": "BI summary complete."})
    except Exception as e:
        exec_time = time.time() - start_time
        _sync_log_task("bi_engineer", "ERROR", exec_time)
        state["status"] = "ERROR"
        state["errors"].append(str(e))
        _sync_broadcast(connection_key, "bi_engineer", "ERROR", {"message": str(e)})
    return state
def execute_predictive_forecaster(state: SwarmState) -> SwarmState:
    start_time = time.time()
    connection_key = state.get("connection_key")
    _sync_broadcast(connection_key, "predictive_forecaster", "RUNNING", {"message": "Generating forecast."})
    try:
        try:
            from backend.agents.predictive_forecaster import generate_forecast
        except ImportError:
            from agents.predictive_forecaster import generate_forecast
        # AI-08: mechanical follow-up -- see execute_bi_engineer's comment above.
        state["results"]["predictive_forecaster"] = generate_forecast(
            state["client_id"], conversation_history=state.get("conversation_history") or [],
        )
        state["status"] = "COMPLETE"
        exec_time = time.time() - start_time
        _sync_log_task("predictive_forecaster", "COMPLETE", exec_time)
        _sync_broadcast(connection_key, "predictive_forecaster", "COMPLETE", {"message": "Forecast complete."})
    except Exception as e:
        exec_time = time.time() - start_time
        _sync_log_task("predictive_forecaster", "ERROR", exec_time)
        state["status"] = "ERROR"
        state["errors"].append(str(e))
        _sync_broadcast(connection_key, "predictive_forecaster", "ERROR", {"message": str(e)})
    return state
def execute_saas_strategist(state: SwarmState) -> SwarmState:
    start_time = time.time()
    connection_key = state.get("connection_key")
    _sync_broadcast(connection_key, "saas_strategist", "RUNNING", {"message": "Generating strategy analysis."})
    try:
        try:
            from backend.agents.saas_strategist import generate_strategy
        except ImportError:
            from agents.saas_strategist import generate_strategy
        # AI-08: mechanical follow-up -- see execute_bi_engineer's comment above.
        state["results"]["saas_strategist"] = generate_strategy(
            state["client_id"], conversation_history=state.get("conversation_history") or [],
        )
        state["status"] = "COMPLETE"
        exec_time = time.time() - start_time
        _sync_log_task("saas_strategist", "COMPLETE", exec_time)
        _sync_broadcast(connection_key, "saas_strategist", "COMPLETE", {"message": "Strategy analysis complete."})
    except Exception as e:
        exec_time = time.time() - start_time
        _sync_log_task("saas_strategist", "ERROR", exec_time)
        state["status"] = "ERROR"
        state["errors"].append(str(e))
        _sync_broadcast(connection_key, "saas_strategist", "ERROR", {"message": str(e)})
    return state
def execute_report_generator(state: SwarmState) -> SwarmState:
    start_time = time.time()
    connection_key = state.get("connection_key")
    _sync_broadcast(connection_key, "report_generator", "RUNNING", {"message": "Generating stakeholder report."})
    try:
        try:
            from backend.agents.report_generator import generate_stakeholder_report
        except ImportError:
            from agents.report_generator import generate_stakeholder_report
        # AI-08: mechanical follow-up -- see execute_bi_engineer's comment above.
        state["results"]["report_generator"] = generate_stakeholder_report(
            state["client_id"], conversation_history=state.get("conversation_history") or [],
        )
        state["status"] = "COMPLETE"
        exec_time = time.time() - start_time
        _sync_log_task("report_generator", "COMPLETE", exec_time)
        _sync_broadcast(connection_key, "report_generator", "COMPLETE", {"message": "Stakeholder report complete."})
    except Exception as e:
        exec_time = time.time() - start_time
        _sync_log_task("report_generator", "ERROR", exec_time)
        state["status"] = "ERROR"
        state["errors"].append(str(e))
        _sync_broadcast(connection_key, "report_generator", "ERROR", {"message": str(e)})
    return state
def execute_bi_visualization_architect(state: SwarmState) -> SwarmState:
    start_time = time.time()
    connection_key = state.get("connection_key")
    _sync_broadcast(connection_key, "bi_visualization_architect", "RUNNING", {"message": "Choosing chart type from real ledger data."})
    try:
        try:
            from backend.agents.bi_visualization_architect import execute_task as bi_viz_execute_task
        except ImportError:
            from agents.bi_visualization_architect import execute_task as bi_viz_execute_task
        # AI-08: mechanical follow-up -- see execute_bi_engineer's comment above.
        state["results"]["bi_visualization_architect"] = bi_viz_execute_task(
            state["client_id"], state["query"], conversation_history=state.get("conversation_history") or [],
        )
        state["status"] = "COMPLETE"
        exec_time = time.time() - start_time
        _sync_log_task("bi_visualization_architect", "COMPLETE", exec_time)
        _sync_broadcast(connection_key, "bi_visualization_architect", "COMPLETE", {"message": "Chart recommendation complete."})
    except Exception as e:
        exec_time = time.time() - start_time
        _sync_log_task("bi_visualization_architect", "ERROR", exec_time)
        state["status"] = "ERROR"
        state["errors"].append(str(e))
        _sync_broadcast(connection_key, "bi_visualization_architect", "ERROR", {"message": str(e)})
    return state
def execute_external_telemetry_scout(state: SwarmState) -> SwarmState:
    start_time = time.time()
    connection_key = state.get("connection_key")
    _sync_broadcast(connection_key, "external_telemetry_scout", "RUNNING", {"message": "Mapping schema from sample payload."})
    try:
        try:
            from backend.agents.external_telemetry_scout import execute_task as telemetry_execute_task
        except ImportError:
            from agents.external_telemetry_scout import execute_task as telemetry_execute_task
        # AI-08: mechanical follow-up -- see execute_bi_engineer's comment above.
        state["results"]["external_telemetry_scout"] = telemetry_execute_task(
            state["client_id"], state["query"], state.get("sample_payload"),
            conversation_history=state.get("conversation_history") or [],
        )
        state["status"] = "COMPLETE"
        exec_time = time.time() - start_time
        _sync_log_task("external_telemetry_scout", "COMPLETE", exec_time)
        _sync_broadcast(connection_key, "external_telemetry_scout", "COMPLETE", {"message": "Schema mapping complete."})
    except Exception as e:
        exec_time = time.time() - start_time
        _sync_log_task("external_telemetry_scout", "ERROR", exec_time)
        state["status"] = "ERROR"
        state["errors"].append(str(e))
        _sync_broadcast(connection_key, "external_telemetry_scout", "ERROR", {"message": str(e)})
    return state
def router_node(state: SwarmState) -> SwarmState:
    start_time = time.time()
    query = state.get("query", "").lower()
    connection_key = state.get("connection_key")
    _sync_broadcast(connection_key, "Orchestrator", "ROUTING",
                     {"message": "Determining which specialist should handle this query."})
    routes = [
        ("external_telemetry_scout", ["external telemetry", "external source", "external api", "third-party data", "third party data", "webhook", "telemetry", "sample payload"]),
        ("data_engineer", ["schema", "data", "ingest", "pipeline", "duckdb", "warehouse"]),
        ("bi_visualization_architect", ["chart", "graph", "visualiz", "plot", "recharts"]),
        ("report_generator", ["report", "export", "stakeholder", "pdf", "download"]),
        ("predictive_forecaster", ["forecast", "predict", "projection", "trajectory", "next quarter"]),
        ("saas_strategist", ["pricing", "strategy", "competitor", "competitive", "market position", "elasticity"]),
        ("bi_engineer", ["kpi", "metric", "variance", "dashboard"]),
    ]
    state["active_agent"] = "virtual_cfo"
    for agent_name, keywords in routes:
        if any(keyword in query for keyword in keywords):
            state["active_agent"] = agent_name
            break
    _sync_broadcast(connection_key, "Orchestrator", "ROUTED", {"routed_to": state["active_agent"]})
    exec_time = time.time() - start_time
    _sync_log_task("orchestrator", "COMPLETE", exec_time)
    return state
def determine_route(state: SwarmState) -> str:
    return state.get("active_agent", "virtual_cfo")
workflow = StateGraph(SwarmState)
workflow.add_node("router", router_node)
workflow.add_node("virtual_cfo", execute_virtual_cfo)
workflow.add_node("data_engineer", execute_data_engineer)
workflow.add_node("bi_engineer", execute_bi_engineer)
workflow.add_node("predictive_forecaster", execute_predictive_forecaster)
workflow.add_node("saas_strategist", execute_saas_strategist)
workflow.add_node("report_generator", execute_report_generator)
workflow.add_node("bi_visualization_architect", execute_bi_visualization_architect)
workflow.add_node("external_telemetry_scout", execute_external_telemetry_scout)
workflow.set_entry_point("router")
workflow.add_conditional_edges("router", determine_route, {
    "virtual_cfo": "virtual_cfo",
    "data_engineer": "data_engineer",
    "bi_engineer": "bi_engineer",
    "predictive_forecaster": "predictive_forecaster",
    "saas_strategist": "saas_strategist",
    "report_generator": "report_generator",
    "bi_visualization_architect": "bi_visualization_architect",
    "external_telemetry_scout": "external_telemetry_scout",
})
workflow.add_edge("virtual_cfo", END)
workflow.add_edge("data_engineer", END)
workflow.add_edge("bi_engineer", END)
workflow.add_edge("predictive_forecaster", END)
workflow.add_edge("saas_strategist", END)
workflow.add_edge("report_generator", END)
workflow.add_edge("bi_visualization_architect", END)
workflow.add_edge("external_telemetry_scout", END)
app_graph = workflow.compile()
def _summarize_result(result: Any) -> str:
    if isinstance(result, dict) and result:
        parts = [f"{k}: {v}" for k, v in result.items()]
        return "; ".join(parts)
    if result:
        return str(result)
    return "No result was produced by the routed agent."
# AI-07: previously route_query() didn't return a confidence_score field AT
# ALL, despite the build list's own note describing one as "currently a
# binary complete/error flag (98.5 vs 0.0)". Confirmed live against the real
# frontend: CognitiveSearchBar.tsx and SwarmVisualizer.tsx both declare
# `confidence_score: number` and render it as
# `(confidence_score * 100).toFixed(0)}%` directly from this exact response
# shape, with no fallback for a missing field -- meaning every real search
# result has been rendering "Confidence: NaN%" in production, not a stale
# binary flag. This also closes the SRS FR-9.5 concern the build list
# flagged: no number is fabricated or presented as more statistically
# meaningful than it is.
#
# Definition (deliberately simple and auditable, not a bespoke per-agent
# calibration exercise):
#   - The routed agent's own result is missing, not a dict, or its status is
#     an explicit failure/empty-data state (ERROR, NO_DATA,
#     COULD_NOT_ANSWER, INSUFFICIENT_HISTORY, NO_QUESTION_ASKED) -> 0.0.
#     There is no confidence to report in a response that couldn't actually
#     answer the query.
#   - predictive_forecaster specifically: its own r_squared IS a real,
#     already-computed statistical confidence value (goodness-of-fit of the
#     linear trend) -- used directly rather than inventing a second number
#     that would just have to agree with it or look inconsistent.
#   - Every other agent on a genuine success path: 1.0. This is NOT a
#     statistical certainty measure -- most of these agents are
#     deterministic DB queries plus an optional LLM narrative layer, not
#     statistical models. It means "a real, DB-computed answer was
#     produced," not "the model is 100% certain." It does not yet
#     distinguish a real-data-plus-real-LLM-narrative response from a
#     real-data-plus-template-fallback-narrative response (both return the
#     same real, correct numbers either way -- see each agent's own
#     fallback template) -- that finer-grained distinction is a reasonable
#     future refinement, not something this value silently claims to
#     capture today.
_CONFIDENCE_FAILURE_STATUSES = {"ERROR", "NO_DATA", "COULD_NOT_ANSWER", "INSUFFICIENT_HISTORY", "NO_QUESTION_ASKED"}
def _compute_confidence_score(agent_name: str, agent_result: Any) -> float:
    if not isinstance(agent_result, dict):
        return 0.0
    result_status = agent_result.get("status")
    if result_status in _CONFIDENCE_FAILURE_STATUSES:
        return 0.0
    if agent_name == "predictive_forecaster":
        r_squared = agent_result.get("r_squared")
        if isinstance(r_squared, (int, float)):
            return round(float(r_squared), 4)
    return 1.0
def route_query(
    query: str, client_id: str, session_id: Optional[str] = None,
    sample_payload: Optional[Any] = None, user_id: Optional[int] = None,
) -> dict:
    """
    SQL-03 (27 Aug 2026): `user_id` (optional, default None) is the
    authenticated user who issued this query, when known -- carried through
    SwarmState into execute_bi_engineer so the query_audit trail can
    attribute the eventual audit row to a real user, not just a tenant.
    Callers that omit it (e.g. tooling/regression scripts) are unaffected;
    the audit row's user_id is simply NULL in that case, exactly as before
    this parameter existed.
    """
    connection_key = f"{client_id}:{session_id}" if session_id else None
    # Track 4: fetch this session's recent history BEFORE the graph runs so
    # a routed agent can ground a follow-up question in what was actually
    # asked/answered before. No session_id (e.g. a stateless API call) ->
    # empty history, same behavior as before this track existed.
    conversation_history = _sync_get_history(client_id, session_id)
    initial_state: SwarmState = {
        "client_id": client_id,
        "query": query,
        "active_agent": "router",
        "results": {},
        "status": "PENDING",
        "errors": [],
        "connection_key": connection_key,
        "sample_payload": sample_payload,
        "session_id": session_id,
        "conversation_history": conversation_history,
        "user_id": user_id,
    }
    final_state = app_graph.invoke(initial_state)
    active_agent = final_state.get("active_agent")
    agent_result = final_state.get("results", {}).get(active_agent)
    synthesized_insight = _summarize_result(agent_result)
    # Persist this exchange for the NEXT turn in this session. Logged after
    # the graph completes, and logs whatever actually happened (including an
    # ERROR-status turn) -- never fabricates a success turn that didn't occur.
    _sync_log_turn(client_id, session_id, "user", query)
    _sync_log_turn(client_id, session_id, "assistant", synthesized_insight, agent_name=active_agent)
    # ENT-03: one real, hash-chained lineage entry per routed query -- the
    # platform-wide "every query path" audit trail query_audit (SQL-03)
    # never covered, since that table only ever logged BI Engineer's own
    # NL-to-SQL requests. model_used is left unset here: each agent module
    # picks its own model internally (model_registry.get_model) and that
    # choice isn't surfaced back up to this scope today -- a reasonable
    # future refinement, not silently guessed here.
    final_status = final_state.get("status", "UNKNOWN")
    decision_summary = f"Routed to '{active_agent}'. {synthesized_insight}"[:2000]
    log_lineage_entry_sync(
        client_id=client_id,
        agent_name=active_agent,
        query_text=query,
        decision_summary=decision_summary,
        status=final_status,
        session_id=session_id,
    )
    return {
        "query": query,
        "synthesized_insight": synthesized_insight,
        "agent_breakdown": [
            {
                "agent_name": active_agent,
                "domain": "Enterprise Intelligence",
                "output_summary": str(final_state.get("results")),
            }
        ],
        "confidence_score": _compute_confidence_score(active_agent, agent_result),
        "status": final_state.get("status")
    }