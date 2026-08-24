#!/usr/bin/env python3
"""
AI-04: model regression-evaluation harness.

Run this BEFORE rolling out a model-version change for any agent (e.g.
swapping "gpt-4o" for a newer snapshot, or gpt-4o-mini for a different
model entirely). It calls the SAME real agent function twice against the
SAME real tenant data -- once with whatever model is currently pinned in
model_registry.py (the baseline), once with a CANDIDATE model you name --
and reports two genuinely different things, kept separate on purpose:

  1. COMPUTED VALUES (numbers that come from Python/SQL, never from the
     LLM -- e.g. gross_margin, total_revenue, r_squared) must be IDENTICAL
     between the two runs, because the model has no way to influence them
     at all. If they differ, that's a hard FAIL pointing at a bug in this
     harness or in the agent's own code path -- NOT a model-quality
     judgment call.

  2. SHAPE VALIDITY of the LLM-authored narrative (insights/projections/
     strategies/the query-intent JSON/etc.) -- does the candidate model's
     raw response still pass the SAME shape check the agent itself already
     uses to decide "trust this LLM output" vs. "fall back to the
     template"? This is the actionable AI-04 signal: "the new model
     stopped returning the expected JSON shape," not "the new model's
     wording is different" (wording differences are real, expected, and
     not something this script judges -- read the actual insights
     yourself for that).

This is NOT an offline/mocked test -- it needs a real OPENAI_API_KEY and
network access to mean anything, since it's comparing two REAL models'
real behavior. Run it from the project root:

    python3 backend/tools/model_regression_check.py <agent_key> <candidate_model> [--tenant CLIENT_ID]

agent_key must be one of the keys in model_registry.AGENT_MODELS.
"""
import sys
import os
import argparse

try:
    from backend import model_registry
except ImportError:
    import model_registry


def _diff_computed_values(baseline: dict, candidate: dict, computed_keys) -> list:
    """
    Returns a list of (key, baseline_value, candidate_value) for every
    computed_keys entry whose value differs between the two runs. A
    computed_keys entry may be a dotted path (e.g. "metrics.gross_margin")
    to reach a nested dict.
    """
    diffs = []
    for key in computed_keys:
        parts = key.split(".")
        b, c = baseline, candidate
        try:
            for p in parts:
                b = b[p]
                c = c[p]
        except (KeyError, TypeError, IndexError):
            diffs.append((key, "<missing>", "<missing>"))
            continue
        if isinstance(b, float) and isinstance(c, float):
            if abs(b - c) > 1e-6:
                diffs.append((key, b, c))
        elif b != c:
            diffs.append((key, b, c))
    return diffs


def compare_model_versions(agent_key, run_fn, candidate_model, computed_keys=None, shape_validator=None, baseline_model=None):
    """
    agent_key: the model_registry.py key to temporarily override.
    run_fn: zero-arg callable that invokes the real agent function and
        returns its result dict (the caller closes over client_id/query/
        whatever else the specific agent function needs).
    candidate_model: the model string to test as the "after" run.
    computed_keys: list of (possibly dotted) keys that must be byte-
        identical between baseline and candidate, since they're computed
        in Python/SQL and the model can't influence them. Omit to skip
        computed-value comparison.
    shape_validator: optional callable(result_dict) -> bool, the SAME
        shape check the agent itself uses internally to decide whether to
        trust the LLM's raw output. Omit to skip shape-regression
        detection.
    baseline_model: model string for the "before" run. Defaults to
        whatever's currently pinned in model_registry.py for this
        agent_key (the normal case -- comparing "what's live today" to
        "what I'm considering switching to").

    Returns a report dict. Restores the original registry entry when
    done, even on error.
    """
    original_model = model_registry.AGENT_MODELS[agent_key]
    actual_baseline = baseline_model or original_model
    try:
        model_registry.AGENT_MODELS[agent_key] = actual_baseline
        baseline_result = run_fn()

        model_registry.AGENT_MODELS[agent_key] = candidate_model
        candidate_result = run_fn()
    finally:
        model_registry.AGENT_MODELS[agent_key] = original_model

    report = {
        "agent_key": agent_key,
        "baseline_model": actual_baseline,
        "candidate_model": candidate_model,
        "baseline_result": baseline_result,
        "candidate_result": candidate_result,
    }

    if computed_keys:
        diffs = _diff_computed_values(baseline_result, candidate_result, computed_keys)
        report["computed_value_diffs"] = diffs
        report["computed_values_identical"] = len(diffs) == 0
    else:
        report["computed_value_diffs"] = None
        report["computed_values_identical"] = None

    if shape_validator is not None:
        baseline_valid = bool(shape_validator(baseline_result))
        candidate_valid = bool(shape_validator(candidate_result))
        report["baseline_shape_valid"] = baseline_valid
        report["candidate_shape_valid"] = candidate_valid
        # The actionable signal: baseline was fine, candidate broke -- a
        # real regression worth blocking the rollout over. A candidate
        # that's invalid when baseline was ALSO invalid isn't a new
        # regression (something else is already wrong, e.g. no API key in
        # this environment) -- surfaced via the two booleans above, but not
        # flagged as "shape_regression" on its own.
        report["shape_regression"] = baseline_valid and not candidate_valid
    else:
        report["baseline_shape_valid"] = None
        report["candidate_shape_valid"] = None
        report["shape_regression"] = None

    return report


def print_report(report: dict):
    print(f"\n=== Model regression check: {report['agent_key']} ===")
    print(f"  baseline:  {report['baseline_model']}")
    print(f"  candidate: {report['candidate_model']}")
    if report["computed_values_identical"] is not None:
        if report["computed_values_identical"]:
            print("  [OK] All computed values identical between runs (as expected -- the model can't affect these).")
        else:
            print("  [FAIL] Computed values DIFFERED between runs -- this points at a bug, not a model-quality issue:")
            for key, b, c in report["computed_value_diffs"]:
                print(f"         {key}: baseline={b!r} candidate={c!r}")
    if report["shape_regression"] is not None:
        if report["shape_regression"]:
            print("  [FAIL] Candidate model's response FAILED the agent's own shape validation where baseline PASSED.")
            print("         This means the candidate model's raw output stopped matching the expected JSON shape --")
            print("         the agent would silently fall back to its template response in production.")
        elif not report["candidate_shape_valid"]:
            print("  [WARN] Candidate shape invalid, but baseline was ALSO invalid (likely no live LLM configured in this run) -- not a new regression.")
        else:
            print("  [OK] Candidate model's response still passes the agent's own shape validation.")


# -----------------------------------------------------------------------
# Per-agent dispatch table for the CLI. Each entry: run/computed_keys/
# shape_validator, as described in compare_model_versions() above.
#
# IMPORTANT, discovered while building this harness: several agents
# (virtual_cfo, data_engineer, predictive_forecaster) have an internal
# template-fallback that reconstructs a FULLY VALID outer response shape
# even when the LLM's raw JSON was malformed -- that's the fallback
# working exactly as designed (never hand a caller a broken response), but
# it means "shape regression" is NOT observable from their returned dict
# at all: a well-formed template look identical to a well-formed LLM
# response from the outside. For these three, shape_validator is
# deliberately None below rather than a check that would always pass --
# claiming a capability the harness doesn't actually have would be worse
# than admitting the gap. Their computed_keys comparison is unaffected and
# remains a real, meaningful check.
#
# Three agents DO expose a genuine, CODE-ASSIGNED (not LLM-echoed) marker
# distinguishing the two paths -- bi_engineer_distribution's
# status="OPTIMIZED" (LLM success) vs "FALLBACK" (template), the same
# pattern in report_generator ("GENERATED" vs "FALLBACK") and
# saas_strategist ("OPTIMIZED" vs "FALLBACK") -- but only report_generator
# and saas_strategist's FALLBACK value is code-assigned; their "success"
# status string is requested from the LLM inside the required-JSON
# template rather than overwritten by the agent code afterward, so it is
# a strong best-effort signal (the LLM is shown it as a fixed literal, not
# a placeholder) but not as airtight as bi_engineer_distribution's, where
# the code itself assigns "OPTIMIZED"/"FALLBACK" and never trusts an
# LLM-echoed status at all. For report_generator/saas_strategist the
# validator ALSO re-checks the real structural contract, since their
# FALLBACK response passes that structural contract too and would
# otherwise look shape-valid on its own.
#
# ops_shield's own fail-closed design returns a fully-valid
# {"status": "THREAT_DETECTED", ...} shape on ANY internal error (a
# deliberate security property, not a bug) -- so checking status alone
# would ALSO always pass, the same masking problem. Its except block does
# use one fixed literal reason string ("Firewall system offline. Access
# denied.") that a genuine LLM verdict cannot plausibly produce, so that's
# used as the real distinguishing signal instead of status alone.
#
# bi_visualization_architect/external_telemetry_scout's actual failure
# return value is an EMPTY insights list (confirmed by reading both
# _summarize_with_llm functions) -- the previous shape_validator here only
# checked isinstance(..., list), which would have incorrectly accepted
# that empty-list failure case as "shape valid".
# -----------------------------------------------------------------------
def _build_dispatch():
    try:
        from backend.agents import virtual_cfo, report_generator, predictive_forecaster, saas_strategist, data_engineer, bi_engineer, ops_shield, bi_visualization_architect, external_telemetry_scout
    except ImportError:
        from agents import virtual_cfo, report_generator, predictive_forecaster, saas_strategist, data_engineer, bi_engineer, ops_shield, bi_visualization_architect, external_telemetry_scout

    def _list_field_nonempty(field_name):
        def _check(result):
            val = result.get(field_name)
            return isinstance(val, list) and len(val) > 0
        return _check

    def _report_generator_shape_valid(result):
        return report_generator._validate_report_shape(result) and result.get("status") == "GENERATED"

    def _saas_strategist_shape_valid(result):
        strategies = result.get("strategies")
        return isinstance(strategies, list) and len(strategies) > 0 and result.get("status") == "OPTIMIZED"

    def _bi_engineer_distribution_shape_valid(result):
        return result.get("status") == "OPTIMIZED"

    def _ops_shield_shape_valid(result):
        if not isinstance(result, dict) or result.get("status") not in ("SECURE", "THREAT_DETECTED"):
            return False
        # This exact string is the agent's own fixed fail-closed literal
        # (see ops_shield.py's except block) -- a real LLM verdict cannot
        # plausibly reproduce it, so its presence means the candidate
        # crashed/mismatched shape and fail-closed kicked in, not that it
        # rendered a genuine security judgment.
        return result.get("reason") != "Firewall system offline. Access denied."

    return {
        "virtual_cfo": {
            "run": lambda client_id: virtual_cfo.generate_cfo_briefing(client_id),
            "computed_keys": ["metrics.gross_margin", "metrics.burn_rate", "metrics.cash_runway_months", "assumed_cash_reserves"],
            # No distinguishing marker between LLM-success and template-
            # fallback for this agent -- see module-level note above.
            # computed_keys comparison above remains fully valid.
            "shape_validator": None,
        },
        "report_generator": {
            "run": lambda client_id: report_generator.generate_stakeholder_report(client_id),
            "computed_keys": ["summary_metrics.total_revenue", "summary_metrics.total_expenses", "summary_metrics.net_income", "summary_metrics.records_audited"],
            "shape_validator": _report_generator_shape_valid,
        },
        "predictive_forecaster": {
            "run": lambda client_id: predictive_forecaster.generate_forecast(client_id),
            "computed_keys": ["baseline_revenue", "r_squared", "projected_growth_rate", "projected_q4_revenue"],
            # Both the LLM-success and template-fallback paths use
            # status="FORECASTED" -- no distinguishing marker. See note above.
            "shape_validator": None,
        },
        "saas_strategist": {
            "run": lambda client_id: saas_strategist.generate_strategy(client_id),
            "computed_keys": [],
            "shape_validator": _saas_strategist_shape_valid,
        },
        "data_engineer": {
            "run": lambda client_id: data_engineer.analyze_schema_quality(client_id),
            "computed_keys": [],
            # Both the LLM-success and template-fallback paths use
            # status="OPTIMIZED" -- no distinguishing marker. See note above.
            "shape_validator": None,
        },
        "bi_engineer_distribution": {
            "run": lambda client_id: bi_engineer.generate_bi_summary(client_id, "what are our top spending categories?"),
            "computed_keys": ["total_records"],
            "shape_validator": _bi_engineer_distribution_shape_valid,
        },
        "ops_shield": {
            "run": lambda client_id: ops_shield.analyze_threat(client_id, "What was our revenue last month?"),
            "computed_keys": [],
            "shape_validator": _ops_shield_shape_valid,
        },
        "bi_visualization_architect": {
            "run": lambda client_id: {"insights": bi_visualization_architect._summarize_with_llm(client_id, "show revenue by category", "pie", {}, {})},
            "computed_keys": [],
            "shape_validator": _list_field_nonempty("insights"),
        },
        "external_telemetry_scout": {
            "run": lambda client_id: {"insights": external_telemetry_scout._summarize_with_llm(client_id, "map this payload", {"field": "VARCHAR"}, {"field": "sample"})},
            "computed_keys": [],
            "shape_validator": _list_field_nonempty("insights"),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("agent_key", choices=sorted(model_registry.AGENT_MODELS.keys()))
    parser.add_argument("candidate_model")
    parser.add_argument("--tenant", default="verify_tenant", help="Real client_id to run both models against (default: verify_tenant).")
    parser.add_argument("--baseline-model", default=None, help="Override the baseline model (default: whatever's currently pinned in model_registry.py).")
    args = parser.parse_args()

    dispatch = _build_dispatch()
    entry = dispatch.get(args.agent_key)
    if entry is None:
        print(f"No CLI dispatch entry for agent_key '{args.agent_key}' yet -- use compare_model_versions() directly for this one.")
        sys.exit(1)

    report = compare_model_versions(
        args.agent_key,
        lambda: entry["run"](args.tenant),
        candidate_model=args.candidate_model,
        computed_keys=entry["computed_keys"],
        shape_validator=entry["shape_validator"],
        baseline_model=args.baseline_model,
    )
    print_report(report)
    if report["computed_values_identical"] is False or report["shape_regression"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
