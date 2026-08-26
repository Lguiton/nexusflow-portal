# AI-04: centralized per-agent model registry + version-change log.
#
# Previously every agent file hardcoded its OpenAI model string inline at
# its own .chat.completions.create() call site -- 9 call sites spread
# across 8 files, no single place to see "what model is agent X pinned to
# right now," and no way to change one without hunting through a system-
# prompt-adjacent function body. This is that single source of truth.
# Swapping a model going forward is a one-line edit here plus a
# REGISTRY_CHANGELOG entry, not a buried inline text edit.
#
# Pairs with tools/model_regression_check.py: that harness temporarily
# overrides an entry here to run a candidate model's REAL output against
# the currently-pinned baseline, on the same real tenant data, BEFORE you
# edit this file to roll a model change out for real.

AGENT_MODELS = {
    "virtual_cfo": "gpt-4o",
    "bi_engineer_query_intent": "gpt-4o-mini",
    "bi_engineer_distribution": "gpt-4o",
    "data_engineer": "gpt-4o-mini",
    "saas_strategist": "gpt-4o",
    "report_generator": "gpt-4o",
    "predictive_forecaster": "gpt-4o",
    "ops_shield": "gpt-4o-mini",
    "bi_visualization_architect": "gpt-4o-mini",
    "external_telemetry_scout": "gpt-4o-mini",
    # Track 3 (persistent vector RAG): embedding model, not a chat model --
    # 1536-dim output, which app/core/rag.py's Qdrant collection is sized
    # for. Changing this later means re-embedding every existing document,
    # not just updating this entry -- flag that explicitly if it ever
    # changes.
    "knowledge_base_embedding": "text-embedding-3-small",
}

# One entry per deliberate model change -- append, never rewrite history.
# This is the audit trail half of AI-04's "regression evaluation": a
# record of WHEN a pinned model changed and why, not just what it is
# today. Update this BY HAND alongside AGENT_MODELS whenever you actually
# change a pinned model (a real timestamp isn't available at config-
# authoring time the way it is at runtime, so this is a manually
# maintained log, not an automatically stamped one).
REGISTRY_CHANGELOG = [
    {"date": "2026-08-23", "agent_key": "virtual_cfo", "model": "gpt-4o", "note": "Migrated from inline hardcoding to centralized registry -- model unchanged."},
    {"date": "2026-08-23", "agent_key": "bi_engineer_query_intent", "model": "gpt-4o-mini", "note": "Migrated from inline hardcoding to centralized registry -- model unchanged."},
    {"date": "2026-08-23", "agent_key": "bi_engineer_distribution", "model": "gpt-4o", "note": "Migrated from inline hardcoding to centralized registry -- model unchanged."},
    {"date": "2026-08-23", "agent_key": "data_engineer", "model": "gpt-4o-mini", "note": "Migrated from inline hardcoding to centralized registry -- model unchanged."},
    {"date": "2026-08-23", "agent_key": "saas_strategist", "model": "gpt-4o", "note": "Migrated from inline hardcoding to centralized registry -- model unchanged."},
    {"date": "2026-08-23", "agent_key": "report_generator", "model": "gpt-4o", "note": "Migrated from inline hardcoding to centralized registry -- model unchanged."},
    {"date": "2026-08-23", "agent_key": "predictive_forecaster", "model": "gpt-4o", "note": "Migrated from inline hardcoding to centralized registry -- model unchanged."},
    {"date": "2026-08-23", "agent_key": "ops_shield", "model": "gpt-4o-mini", "note": "Migrated from inline hardcoding to centralized registry -- model unchanged."},
    {"date": "2026-08-23", "agent_key": "bi_visualization_architect", "model": "gpt-4o-mini", "note": "Migrated from inline hardcoding to centralized registry -- model unchanged."},
    {"date": "2026-08-23", "agent_key": "external_telemetry_scout", "model": "gpt-4o-mini", "note": "Migrated from inline hardcoding to centralized registry -- model unchanged."},
    {"date": "2026-08-26", "agent_key": "knowledge_base_embedding", "model": "text-embedding-3-small", "note": "New entry -- backing the real persistent vector RAG knowledge base (app/core/rag.py), replacing the previous hardcoded fake 4-dim vector stub."},
]


def get_model(agent_key: str) -> str:
    """
    Returns the currently-pinned model for this agent key. Raises KeyError
    for an unregistered key rather than silently defaulting -- an agent
    that forgets to register itself here should fail loudly at call time,
    not silently fall back to some guessed default model that nobody
    consciously chose.
    """
    return AGENT_MODELS[agent_key]
