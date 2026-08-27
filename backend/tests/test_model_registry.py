"""
Real tests for backend/model_registry.py (AI-04). No DB/network involved
-- pure config module.
"""
import pytest

from backend import model_registry


def test_get_model_returns_pinned_model_for_known_agent():
    assert model_registry.get_model("virtual_cfo") == "gpt-4o"
    assert model_registry.get_model("data_engineer") == "gpt-4o-mini"


def test_get_model_raises_for_unregistered_agent_key():
    with pytest.raises(KeyError):
        model_registry.get_model("totally_made_up_agent")


def test_every_registered_agent_has_a_changelog_entry():
    """
    REGISTRY_CHANGELOG is meant to be the audit trail of every deliberate
    model change -- every key currently in AGENT_MODELS should have at
    least one changelog entry (even if it's just the initial migration
    entry), otherwise the "audit trail" claim in model_registry.py's own
    module docstring silently stops being true as new agents get added.
    """
    changelog_keys = {entry["agent_key"] for entry in model_registry.REGISTRY_CHANGELOG}
    missing = set(model_registry.AGENT_MODELS.keys()) - changelog_keys
    assert not missing, f"Agent(s) with no changelog entry at all: {missing}"


def test_changelog_entries_reference_only_currently_pinned_or_historical_models():
    """Every changelog entry's model string should be a real, plausible
    model identifier -- catches an obvious typo (e.g. 'gtp-4o') in a
    manually-maintained log.

    FIXED 2026-08-26: this used to assert startswith("gpt-") unconditionally,
    which was true only as long as every registered agent was a chat model.
    It started failing for a real, legitimate entry the moment
    "knowledge_base_embedding" (backing app/core/rag.py's persistent vector
    RAG) was registered with "text-embedding-3-small" -- a real OpenAI
    embedding model, not a typo. Broadened to a whitelist of real OpenAI
    model-family prefixes instead of narrowing back to chat-only, so this
    still catches an actual typo (e.g. "gtp-4o", "text-embeding-3-small")
    without breaking every time a legitimate non-chat model is added.
    """
    valid_prefixes = ("gpt-", "o1-", "o3-", "text-embedding-")
    for entry in model_registry.REGISTRY_CHANGELOG:
        assert entry["model"].startswith(valid_prefixes), f"Suspicious model string in changelog: {entry}"
