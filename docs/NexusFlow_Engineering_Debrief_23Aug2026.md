# NexusFlow Analytics — Engineering Debrief & Full Code

**Scope:** Phase 3 tail (AI-04, FIN-01) + Phase 4 (DIFF-03, DIFF-02, DIFF-06, DIFF-05, DIFF-01) — delivered and verified 23 August 2026.
**Companion documents:** `docs/NexusFlow_Master_Build_List_v1.7.docx` (full historical status/backlog), `docs/NexusFlow_Source_of_Truth.docx` Section 10.

This document explains, feature by feature, what was fixed, built, and shipped — the problem before, what changed, why, and how it was verified — followed by the complete, current code for every file touched. Everything below is live on the machine right now; nothing here is a proposal.

---

## Part 1 — What Changed, and Why

### AI-04 — Model/version registry and regression evaluation

**Before:** every agent's OpenAI model string was hardcoded inline at its own `.chat.completions.create()` call site — 9 call sites spread across 8 files. There was no single place to see "what model is agent X pinned to right now," no audit trail of when a model changed, and no way to test a candidate model swap before rolling it out live.

**What was built:** `backend/model_registry.py` centralizes every agent's pinned model into one `AGENT_MODELS` dict plus a `REGISTRY_CHANGELOG` — an append-only log of every deliberate model change and why. `backend/tools/model_regression_check.py` is a CLI harness: it runs the *same real agent function* twice against the *same real tenant data* — once at the currently-pinned baseline model, once at a candidate model — and reports two genuinely different things, kept separate on purpose: (1) whether Python/SQL-computed values (gross margin, revenue totals, r-squared) stayed byte-identical, since the model has zero ability to influence them (a difference there is a code bug, not a model-quality question), and (2) whether the candidate model's raw output still passes the *same* shape-validation check the agent itself already uses internally to decide "trust this JSON" vs. "fall back to the template." The harness is explicit about what it *can't* detect: for `virtual_cfo`, `predictive_forecaster`, and `data_engineer`, the internal template fallback reconstructs a fully valid response shape even when the LLM output was malformed, so a shape check can't distinguish "real LLM success" from "silently fell back" for those three agents — `shape_validator` is deliberately left `None` for them rather than a check that would always pass.

**Verification:** 3 targeted checks in the stub harness confirm the diffing logic itself (distinguishing "wording changed" from "a computed value changed" or "the shape broke"), and that the registry is always restored to its original state afterward, even on error. Real model-quality comparison needs a live `OPENAI_API_KEY` and network access — that's a documented limit of the harness, not a gap in the harness's own logic.

### FIN-01 — Formal MRR definition and ground-truth test suite

**Before:** there was no real MRR figure anywhere in the product — only a "Monthly Revenue" number that summed all transactions for the current month regardless of whether they were recurring.

**What was built:** `get_mrr_summary()` in `db_manager.py` computes real Monthly Recurring Revenue from exactly one source: transactions a tenant explicitly flagged `recurring`/`is_recurring` on upload. A tenant that has never provided that flag on any upload gets `mrr_available: false` and `mrr: null` — never silently backfilled from the existing "Monthly Revenue" figure, never guessed from category names. A tenant that *has* provided the flag gets a real number, including a genuine `$0.00` if nothing is currently flagged recurring for the current month — that's a real answer, not a missing one. The distinction between "unavailable" and "genuinely zero" is the whole point of the honesty guarantee here.

**Verification:** `run_verify_fin01_mrr.py` — real end-to-end ingest-to-MRR correctness, plus a specific test confirming a tenant correctly *reverts* to `mrr_available: false` if a later upload omits the flag (i.e., the flag isn't sticky/cached incorrectly).

### DIFF-03 — "What I don't know yet" panel

**Before:** the dashboard only ever showed what NexusFlow *could* compute — there was no surface telling a tenant what it *couldn't* compute yet, and why.

**What was built:** `backend/gaps.py`'s `get_known_gaps()` combines three always-true structural gaps (no customer-identity column, no evidence trail — now partially closed by DIFF-01 below, AI usage not tenant-scoped) with data-dependent gaps computed from signals that already existed and are cheap to check (`get_ledger_chart_context`, `get_mrr_summary`, `get_forecast_accuracy`). It deliberately never calls an LLM-backed agent just to check an availability flag — that would mean a real API cost on every dashboard load to answer a question the existing data-only signals already answer. Frontend: `KnownGapsPanel.tsx`.

**Verification:** 21 checks in `run_verify_diff02_diff03.py`.

### DIFF-02 — Assumption ledger

**Before:** several real financial-calculation constants (e.g. the assumed cash-reserve figure feeding cash-runway) existed in code but were invisible to the user — a runway figure looked like a real bank-balance-driven calculation with no disclosure that it depends on a placeholder.

**What was built:** `backend/assumptions.py`'s `_build_assumptions()` reads every numeric constant **live** from the exact module attributes the real calculations use (`virtual_cfo.ASSUMED_CASH_RESERVES`, `predictive_forecaster.MIN_PERIODS_FOR_FORECAST`, and five others) — never a hand-copied duplicate that could silently drift out of sync the moment someone tunes a threshold — plus five qualitative methodology notes (how revenue/COGS/OPEX are classified, what MRR actually means, why the churn signal is a revenue-risk proxy and not real churn, etc.). Frontend: `AssumptionLedger.tsx`.

### DIFF-06 — Deterministic auto-categorization suggestions

**Before:** an uncategorized transaction stayed uncategorized until a human manually fixed it — no assistance, and no appetite for an LLM guess that could be wrong with no accountability trail.

**What was built:** `_suggest_category_for()` reduces a transaction's description to its significant words (lowercased, punctuation stripped, stopwords and short/numeric tokens dropped) and matches it against the same reduction of every other **already-categorized row for that same tenant** — never another tenant's data, never an LLM. The category with the most keyword-overlapping votes wins, with a real `confidence` (the fraction of matching rows that agree) and a real `matched_row_count` — both shown to the user, never hidden. `suggest_category_fixes()` runs this for every currently-"Uncategorized" row a tenant has. `apply_category_suggestion()` requires an explicit `row_id` (built by DIFF-01) and updates exactly one row — cross-tenant writes and nonexistent row_ids are both rejected, verified. Exposed via `backend/categorization.py`. Frontend: `CategorySuggestionsWidget.tsx`, with an explicit **Accept** button per suggestion — nothing is ever auto-applied.

**Verification:** 12 of 30 checks in `run_verify_diff01_diff06.py` — keyword-match/no-match/majority-vote unit tests, plus a full end-to-end flow (ingest → suggest → accept → confirm the category actually changed → confirm no more suggestions remain for that row) including cross-tenant-write-blocked and input-validation checks.

### DIFF-05 — Guided first-insight onboarding (lightweight checklist)

**Founder decision (2026-08-23):** a lightweight progress checklist, not a full guided modal tour.

**What was built:** `OnboardingChecklist.tsx` is pure frontend — it derives three checklist items (upload data, MRR unlocked, forecast unlocked) entirely by reusing two endpoints that already existed (`/api/v1/finance/kpi-summary` and `/api/v1/insights/known-gaps`). No new backend endpoint was needed. Every item's status (`done` / `available` / `locked`) is derived from real signals — never a fabricated "you did this" flag.

### DIFF-01 — Evidence trail (row-level drill-down)

**Founder decision (2026-08-23):** add a real row ID now, as a schema migration — the same pattern already established for FIN-01's `is_recurring` column.

**What was built:** a sequence-backed `row_id BIGINT` column was added to `ledgers` via an idempotent migration (`CREATE SEQUENCE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN` guarded by a `PRAGMA table_info` check, and a one-time backfill `UPDATE` for pre-existing rows) inside `init_db()`. Every future ingest also assigns a fresh, genuinely distinct `row_id` per row via `nextval('ledger_row_id_seq')` in the INSERT itself — standard SQL sequence semantics guarantee a new value is drawn per row emitted, never one value reused. `get_ledger_rows()` is a new drill-down function: given an optional category/month filter, it returns the exact ledger rows behind that filter, each carrying its real `row_id`. Pre-migration "legacy" rows with no `row_id` are surfaced honestly via a `legacy_row_count` field, never hidden or silently relabeled. Exposed via `backend/evidence.py`. Frontend: `LedgerRowExplorer.tsx`.

**Explicit scope note (preserved in `evidence.py`'s own docstring):** this does **not** rewrite every agent's LLM narrative to cite `row_id`s inline — that's a separate, larger future step. What exists today is a standalone drill-down explorer, not yet a click-through from every chart/insight elsewhere on the dashboard.

**Verification:** 18 of 30 checks in `run_verify_diff01_diff06.py` — row_id distinctness and non-null-ness on ingest, every drill-down filter combination (category only, month only, both, neither), cross-tenant isolation (a tenant with no rows never sees another tenant's data), legacy-row honesty, and a direct test of the backfill UPDATE's semantics.

### Overall verification methodology

Every backend change ran against the existing stub-based test harness: **10 test suites, ~200 checks total across the full regression sweep, zero failures**, plus 30 new checks specific to DIFF-01/DIFF-06 and 21 new checks specific to DIFF-02/DIFF-03. Every frontend change was additionally type-checked with a real `npx tsc --noEmit` run against the **actual project's own** `node_modules` and `tsconfig.json` on the founder's machine — not a sandbox approximation — with **zero errors** both times it was run. Each file was then delivered to the live codebase individually, with a drift check (re-stage, re-diff) immediately before every write, and **zero rejected writes** across the whole session.

---

## Part 2 — Full Code

### Backend — New Files

#### `backend/model_registry.py`

```python
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
```

#### `backend/tools/model_regression_check.py`

```python
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
# at all: a well-formed template looks identical to a well-formed LLM
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
```

#### `backend/assumptions.py`

```python
"""
DIFF-02: Assumption ledger.

Surfaces the REAL, already-disclosed numeric constants and methodology
choices this platform's calculations depend on -- read LIVE from the
modules that actually use them, never hand-copied values that could drift
out of sync with the real code the moment someone tunes a threshold.

Platform-wide, not tenant-scoped -- these are code-level constants, not
per-tenant data. Requires a valid token (same posture as
/api/v1/metrics/ai-usage and friends: authenticated but not yet gated
behind a real admin/RBAC tier -- see metrics.py's own notes on this).
"""
import logging
from fastapi import APIRouter, HTTPException, Depends

try:
    from backend.agents import virtual_cfo, predictive_forecaster
except ImportError:
    from agents import virtual_cfo, predictive_forecaster

try:
    from backend.auth import verify_jwt_and_get_client_id
except ImportError:
    from auth import verify_jwt_and_get_client_id

router = APIRouter()
logger = logging.getLogger("nexusflow.assumptions")


def _build_assumptions() -> dict:
    """
    Separated from the endpoint so it can be unit-tested without spinning
    up FastAPI/JWT machinery -- pure function, no request/auth dependency.
    """
    return {
        "numeric_assumptions": [
            {
                "key": "assumed_cash_reserves",
                "label": "Assumed Cash Reserves",
                "value": virtual_cfo.ASSUMED_CASH_RESERVES,
                "unit": "usd",
                "used_by": "Virtual CFO -- Cash Runway",
                "description": (
                    "Cash runway (assumed_cash_reserves / burn_rate) uses this "
                    "PLACEHOLDER reserve figure, not a real bank balance -- "
                    "NexusFlow has no bank/accounting integration to pull an "
                    "actual cash position from yet. Every runway figure shown "
                    "anywhere is only as real as this number."
                ),
            },
            {
                "key": "min_periods_for_forecast",
                "label": "Minimum Months of History Required to Forecast",
                "value": predictive_forecaster.MIN_PERIODS_FOR_FORECAST,
                "unit": "months",
                "used_by": "Predictive Forecaster",
                "description": (
                    "Fewer distinct months of ledger history than this, and a "
                    "linear trend is not computed -- reported as "
                    "INSUFFICIENT_HISTORY instead of a fabricated projection."
                ),
            },
            {
                "key": "forecast_horizon_months",
                "label": "Forecast Horizon",
                "value": predictive_forecaster.FORECAST_HORIZON_MONTHS,
                "unit": "months",
                "used_by": "Predictive Forecaster",
                "description": "How many months forward each forecast projects.",
            },
            {
                "key": "recent_window_months",
                "label": "Recent-Trend Window (Revenue-Risk Proxy)",
                "value": predictive_forecaster.RECENT_WINDOW_MONTHS,
                "unit": "months",
                "used_by": "Predictive Forecaster -- Revenue-Risk Proxy",
                "description": (
                    "Width of the 'recent' window compared against the overall "
                    "trend to detect growth-rate deceleration."
                ),
            },
            {
                "key": "consecutive_decline_moderate",
                "label": "Moderate-Risk Threshold",
                "value": predictive_forecaster.CONSECUTIVE_DECLINE_MODERATE,
                "unit": "consecutive declining months",
                "used_by": "Predictive Forecaster -- Revenue-Risk Proxy",
                "description": "This many consecutive declining months is flagged MODERATE risk.",
            },
            {
                "key": "consecutive_decline_elevated",
                "label": "Elevated-Risk Threshold",
                "value": predictive_forecaster.CONSECUTIVE_DECLINE_ELEVATED,
                "unit": "consecutive declining months",
                "used_by": "Predictive Forecaster -- Revenue-Risk Proxy",
                "description": "This many consecutive declining months is flagged ELEVATED risk.",
            },
            {
                "key": "materially_declining_pct",
                "label": "Materiality Threshold for Decline",
                "value": predictive_forecaster.MATERIALLY_DECLINING_PCT,
                "unit": "% per month",
                "used_by": "Predictive Forecaster -- Revenue-Risk Proxy",
                "description": (
                    "A recent monthly growth rate below this percentage counts "
                    "as a materially declining trend, not just ordinary noise."
                ),
            },
        ],
        "methodology_notes": [
            {
                "key": "revenue_cogs_opex_classification",
                "label": "Revenue / COGS / OPEX Classification",
                "used_by": "Virtual CFO -- Gross Margin, Burn Rate",
                "description": (
                    "Transactions are classified by sign and a category-name "
                    "keyword heuristic, not a formal chart-of-accounts mapping. "
                    "Gross margin and burn rate are only as accurate as this "
                    "heuristic."
                ),
            },
            {
                "key": "mrr_definition",
                "label": "Monthly Recurring Revenue Definition",
                "used_by": "Finance KPIs",
                "description": (
                    "MRR sums positive-amount transactions a tenant explicitly "
                    "flagged recurring=true, dated in the current calendar "
                    "month. This is transaction-based, not subscription-"
                    "contract-based -- there is no billing-cycle/contract-value "
                    "table to compute 'currently active recurring value' "
                    "independent of what was actually invoiced this month."
                ),
            },
            {
                "key": "revenue_risk_not_churn",
                "label": "Revenue-Risk Proxy Is Not Customer Churn",
                "used_by": "Predictive Forecaster",
                "description": (
                    "The ledgers table has no customer/subscriber-identity "
                    "column, so real per-customer churn cannot be computed. "
                    "What's shown is a tenant-level revenue trend/volatility "
                    "signal instead -- explicitly not churn."
                ),
            },
            {
                "key": "ai_usage_platform_wide",
                "label": "AI Usage & Cost Metrics Are Platform-Wide",
                "used_by": "AI Usage Telemetry",
                "description": (
                    "Token/cost totals are not yet scoped per tenant -- they "
                    "reflect the whole platform, pending real multi-tenant RBAC."
                ),
            },
            {
                "key": "confidence_score_scope",
                "label": "Confidence Score Is Not a Statistical Certainty (Except Forecasts)",
                "used_by": "Cognitive Search / Orchestrator",
                "description": (
                    "confidence_score is a real computed r-squared for "
                    "forecast results, but a simple success/failure signal "
                    "(1.0 or 0.0) for every other agent -- not a calibrated "
                    "probability of correctness."
                ),
            },
        ],
    }


@router.get("/api/v1/assumptions")
async def get_assumptions(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        return _build_assumptions()
    except Exception as e:
        logger.error(f"Failed to build assumption ledger: {e}")
        raise HTTPException(status_code=500, detail="Failed to load assumption ledger")
```

#### `backend/gaps.py`

```python
"""
DIFF-03: "What I don't know yet" panel.

Surfaces REAL, currently-true limitations for a specific tenant -- every
entry here reflects an actual gap in what NexusFlow can currently tell
this tenant, derived from the same cheap, non-LLM signals other endpoints
already compute (get_ledger_chart_context, get_mrr_summary,
get_forecast_accuracy). Deliberately never calls an LLM-backed agent
(cfo-briefing, forecast, bi-summary, etc.) just to check an availability
flag -- that would mean a real network/API cost every time this panel
loads, to answer a question the cheap data-only signals already answer.

Two kinds of gaps: STRUCTURAL (true for every tenant today, because the
schema/product doesn't support it yet -- e.g. no customer-identity column)
and DATA-DEPENDENT (true only because THIS tenant's data doesn't clear a
real threshold yet -- e.g. not enough months of history).
"""
import logging
from fastapi import APIRouter, HTTPException, Depends

try:
    from backend import db_manager
    from backend.agents import predictive_forecaster
    from backend.auth import verify_jwt_and_get_client_id
except ImportError:
    import db_manager
    from agents import predictive_forecaster
    from auth import verify_jwt_and_get_client_id

router = APIRouter()
logger = logging.getLogger("nexusflow.gaps")

_STRUCTURAL_GAPS = [
    {
        "key": "no_customer_identity",
        "title": "Per-customer analytics aren't available",
        "detail": (
            "The ledgers table has no customer/subscriber-identity column, "
            "so active-customer counts and real per-customer churn can't be "
            "computed -- only tenant-level aggregates."
        ),
    },
    {
        "key": "no_evidence_trail",
        "title": "Insights don't yet link back to their exact source rows",
        "detail": (
            "Agent narratives are grounded in real computed numbers, but "
            "there's no way yet to click an insight and see the specific "
            "ledger rows behind it."
        ),
    },
    {
        "key": "ai_usage_not_tenant_scoped",
        "title": "AI usage/cost metrics are platform-wide, not per-tenant",
        "detail": "Token and cost totals reflect the whole platform, not just this tenant, pending real multi-tenant RBAC.",
    },
]


@router.post("/api/v1/insights/known-gaps")
async def get_known_gaps(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        gaps = list(_STRUCTURAL_GAPS)
        context = await db_manager.get_ledger_chart_context(client_id)
        row_count = context.get("row_count", 0)

        if row_count == 0:
            gaps.insert(0, {
                "key": "no_data",
                "title": "No ledger data yet",
                "detail": "Upload a CSV ledger to unlock CFO briefings, forecasts, and every other analysis on this dashboard.",
            })
            return {"client_id": client_id, "row_count": 0, "gaps": gaps}

        mrr_summary = await db_manager.get_mrr_summary(client_id)
        if not mrr_summary.get("mrr_available"):
            gaps.append({
                "key": "mrr_unavailable",
                "title": "Real MRR isn't available yet",
                "detail": "No uploaded row has ever included a 'recurring' or 'is_recurring' column. Include it on your next upload to unlock true Monthly Recurring Revenue.",
            })

        distinct_months = len(context.get("monthly_totals", []))
        if distinct_months < predictive_forecaster.MIN_PERIODS_FOR_FORECAST:
            gaps.append({
                "key": "forecast_insufficient_history",
                "title": "Forecast isn't available yet",
                "detail": f"{distinct_months} distinct month(s) of history on file -- {predictive_forecaster.MIN_PERIODS_FOR_FORECAST} are required before a statistically meaningful trend can be forecast.",
            })

        unparseable = context.get("unparseable_date_count", 0)
        if unparseable:
            gaps.append({
                "key": "unparseable_dates",
                "title": f"{unparseable} transaction(s) have an unrecognized date",
                "detail": "These rows are excluded from every trend, forecast, and monthly figure until their dates are fixed and re-uploaded.",
            })

        accuracy = await db_manager.get_forecast_accuracy(client_id)
        pending_count = len(accuracy.get("pending", [])) if isinstance(accuracy, dict) else 0
        if pending_count:
            gaps.append({
                "key": "forecast_accuracy_pending",
                "title": f"{pending_count} forecast(s) awaiting their target month",
                "detail": "These forecasts haven't been checked against real outcomes yet because their target month hasn't happened. Accuracy will appear here once it has.",
            })

        return {"client_id": client_id, "row_count": row_count, "gaps": gaps}
    except Exception as e:
        logger.error(f"Failed to compute known gaps for tenant '{client_id}': {e}")
        raise HTTPException(status_code=502, detail="Unable to compute known gaps right now.")
```

#### `backend/evidence.py`

```python
"""
DIFF-01: evidence trail / insight-to-source-row linking.

Scope of this pass, stated plainly rather than implied: this gives every
ledger row a real, stable identity (row_id -- see db_manager.init_db's
migration) and a real drill-down endpoint to browse the exact rows behind
a category/month. It does NOT (yet) rewrite every agent's LLM-generated
narrative to cite specific row_ids inline -- that would mean touching each
agent's prompt/response-shape individually, a substantially larger change.
What's here is the real, honest foundation: a genuine way to go from "this
category/month total" to "these are the literal rows that produced it."
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

try:
    from backend import db_manager
    from backend.auth import verify_jwt_and_get_client_id
except ImportError:
    import db_manager
    from auth import verify_jwt_and_get_client_id

router = APIRouter()
logger = logging.getLogger("nexusflow.evidence")


class LedgerRowsRequest(BaseModel):
    category: Optional[str] = None
    month: Optional[str] = None
    limit: int = 200


@router.post("/api/v1/finance/ledger-rows")
async def get_ledger_rows_endpoint(
    req: LedgerRowsRequest = LedgerRowsRequest(),
    client_id: str = Depends(verify_jwt_and_get_client_id),
):
    try:
        return await db_manager.get_ledger_rows(client_id, category=req.category, month=req.month, limit=req.limit)
    except Exception as e:
        logger.error(f"Failed to fetch ledger rows for tenant '{client_id}': {e}")
        raise HTTPException(status_code=502, detail="Unable to load ledger rows right now.")
```

#### `backend/categorization.py`

```python
"""
DIFF-06: auto-categorization suggestions.

Deterministic only, per founder decision (2026-08-23): every suggestion
comes from this SAME tenant's own already-categorized rows via real
keyword overlap (see db_manager._suggest_category_for) -- never an LLM
guess, never auto-applied. The frontend shows each suggestion with its
real confidence and match count; applying one is a separate, explicit,
user-confirmed call targeting one specific row_id (DIFF-01).
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

try:
    from backend import db_manager
    from backend.auth import verify_jwt_and_get_client_id
except ImportError:
    import db_manager
    from auth import verify_jwt_and_get_client_id

router = APIRouter()
logger = logging.getLogger("nexusflow.categorization")


class ApplyCategorySuggestionRequest(BaseModel):
    row_id: int
    new_category: str


@router.post("/api/v1/data/category-suggestions")
async def get_category_suggestions(client_id: str = Depends(verify_jwt_and_get_client_id)):
    try:
        return await db_manager.suggest_category_fixes(client_id)
    except Exception as e:
        logger.error(f"Failed to compute category suggestions for tenant '{client_id}': {e}")
        raise HTTPException(status_code=502, detail="Unable to compute category suggestions right now.")


@router.post("/api/v1/data/apply-category-suggestion")
async def apply_category_suggestion_endpoint(
    req: ApplyCategorySuggestionRequest,
    client_id: str = Depends(verify_jwt_and_get_client_id),
):
    try:
        updated = await db_manager.apply_category_suggestion(client_id, req.row_id, req.new_category)
        if not updated:
            raise HTTPException(
                status_code=404,
                detail="No matching row found for that row_id -- it may belong to a legacy row with no id, a different tenant, or may have already been re-categorized.",
            )
        return {"client_id": client_id, "row_id": req.row_id, "new_category": req.new_category, "updated": True}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to apply category suggestion for tenant '{client_id}': {e}")
        raise HTTPException(status_code=502, detail="Unable to apply category suggestion right now.")
```

### Backend — Changes to Existing Files

#### `backend/main.py` — four new router-include blocks

Added following the exact existing try/except pattern (each new module logs and degrades gracefully if import fails, rather than crashing the whole app):

```python
try:
    from backend import assumptions
    app.include_router(assumptions.router)
except ImportError as e:
    logger.error(f"Failed to load assumptions router: {e}")
try:
    from backend import gaps
    app.include_router(gaps.router)
except ImportError as e:
    logger.error(f"Failed to load gaps router: {e}")
try:
    from backend import evidence
    app.include_router(evidence.router)
except ImportError as e:
    logger.error(f"Failed to load evidence router: {e}")
try:
    from backend import categorization
    app.include_router(categorization.router)
except ImportError as e:
    logger.error(f"Failed to load categorization router: {e}")
```

Everything else in `main.py` (health check, kpi-summary, cfo-briefing, and every other pre-existing endpoint) is unchanged.

#### `backend/db_manager.py` — three changes

**1. `init_db()` — new DIFF-01 migration block**, added immediately after the existing `is_recurring` migration (same idempotent shape: check `PRAGMA table_info`, `ALTER TABLE` only if missing, one-time backfill):

```python
                # DIFF-01: a stable per-row identifier, so an insight (or a
                # user-accepted category suggestion -- see DIFF-06) can
                # reference the EXACT row it came from. Same idempotent
                # migration shape as is_recurring above. A sequence backs
                # both the one-time backfill for pre-existing rows AND
                # every future ingest's fresh inserts (see
                # ingest_csv_to_db) -- nextval() is evaluated once per row
                # in both an INSERT ... SELECT and an UPDATE ... SET,
                # standard SQL sequence semantics, so this assigns a
                # genuinely distinct id per row, never the same value
                # repeated across rows.
                try:
                    conn.execute("CREATE SEQUENCE IF NOT EXISTS ledger_row_id_seq")
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        raise
                if "row_id" not in existing_cols:
                    try:
                        conn.execute("ALTER TABLE ledgers ADD COLUMN row_id BIGINT")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                    # One-time backfill for rows that existed before this
                    # migration -- only runs the first time the column is
                    # added (existing_cols already contains "row_id" on
                    # every subsequent init_db() call, so this block is
                    # skipped then; new rows get their row_id from
                    # ingest_csv_to_db's own INSERT instead).
                    conn.execute("UPDATE ledgers SET row_id = nextval('ledger_row_id_seq') WHERE row_id IS NULL")
```

**2. `ingest_csv_to_db()` — the INSERT statement now assigns `row_id` per row:**

```python
                    # DIFF-01: row_id assigned fresh per row via
                    # nextval('ledger_row_id_seq') -- evaluated once per row
                    # emitted by this multi-row SELECT (standard SQL
                    # sequence semantics), so every inserted row gets a
                    # genuinely distinct id, never a repeated one.
                    conn.execute(
                        "INSERT INTO ledgers (row_id, client_id, date, category, amount, description, is_recurring) "
                        "SELECT nextval('ledger_row_id_seq'), client_id, date, category, amount, description, CAST(is_recurring AS BOOLEAN) FROM clean_df_view"
                    )
```

**3. `get_mrr_summary()` — FIN-01's real MRR calculation (new function):**

```python
async def get_mrr_summary(client_id: str) -> dict:
    """
    FIN-01: real Monthly Recurring Revenue -- computed ONLY from rows this
    tenant explicitly flagged via an uploaded 'is_recurring'/'recurring'
    column (see _parse_recurring_series in ingest_csv_to_db). A tenant that
    has never provided the flag on any upload gets mrr_available=False and
    mrr=None -- never a computed number quietly built from an assumption.
    A tenant that HAS provided it (even if every row is flagged False) gets
    a real number, including a real $0.00 if nothing is currently flagged
    recurring for the current month -- that's a genuine answer, not a
    missing one.

    Definition used here: sum of positive-amount ("amount" > 0, i.e.
    revenue not expenses) transactions flagged is_recurring=TRUE whose date
    falls in the current calendar month. This is a transaction-based
    reading of MRR, the only one this schema can actually support (there is
    no subscription/billing-cycle/customer table to instead sum "currently
    active recurring contract value" independent of what was invoiced this
    specific month) -- disclosed via the returned "note" field rather than
    presented as a more sophisticated definition than the data supports.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    await init_db()
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                flagged_count = conn.execute(
                    "SELECT COUNT(*) FROM ledgers WHERE client_id = ? AND is_recurring IS NOT NULL",
                    [client_id]
                ).fetchone()[0]
                if flagged_count == 0:
                    return {
                        "mrr_available": False,
                        "mrr": None,
                        "recurring_flagged_row_count": 0,
                        "revenue_month": None,
                        "note": (
                            "No uploaded row for this tenant has ever included a "
                            "recurring-vs-one-time flag ('recurring' or 'is_recurring' "
                            "column) -- true MRR is not computable until at least one "
                            "upload provides it. This is different from a tenant with "
                            "zero recurring revenue, which would show $0.00 here, not "
                            "'unavailable'."
                        ),
                    }
                current_month_key = date.today().strftime("%Y-%m")
                mrr_row = conn.execute("""
                    SELECT ROUND(SUM(amount), 2)
                    FROM ledgers
                    WHERE client_id = ?
                      AND is_recurring = TRUE
                      AND amount > 0
                      AND strftime(TRY_CAST(date AS DATE), '%Y-%m') = ?
                """, [client_id, current_month_key]).fetchone()
                mrr = float(mrr_row[0]) if mrr_row[0] is not None else 0.0
                recurring_row_count = conn.execute(
                    "SELECT COUNT(*) FROM ledgers WHERE client_id = ? AND is_recurring = TRUE",
                    [client_id]
                ).fetchone()[0]
                return {
                    "mrr_available": True,
                    "mrr": mrr,
                    "recurring_flagged_row_count": int(recurring_row_count),
                    "revenue_month": current_month_key,
                    "note": (
                        "Real Monthly Recurring Revenue: sum of positive-amount "
                        "(revenue) transactions explicitly flagged recurring=true "
                        "whose date falls in the current calendar month. One-time "
                        "transactions and rows with no recurring flag are excluded, "
                        "not guessed either way."
                    ),
                }
            except Exception as e:
                logger.error(f"Failed to compute MRR summary for tenant '{client_id}': {e}")
                raise
            finally:
                conn.close()
    return await asyncio.to_thread(_query)
```

**4. Four new functions appended to the end of the file — DIFF-01's drill-down and DIFF-06's suggestion engine:**

```python
async def get_ledger_rows(client_id: str, category: str = None, month: str = None, limit: int = 200) -> dict:
    """
    DIFF-01: real row-level drill-down -- returns the actual ledger rows
    (including each row's real row_id) behind an optional category/month
    filter, so a dashboard can show "these are the exact transactions
    behind this number" instead of only a computed aggregate. Omitting
    both filters returns this tenant's most recent rows.

    A single fixed query shape (NULL-safe "(? IS NULL OR ...)" filters)
    is used regardless of which filters are active, rather than building
    different SQL text per combination -- simpler to reason about and to
    test than four distinct query shapes.

    legacy_row_count in the response counts returned rows with no row_id
    (row_id IS NULL) -- rows that existed before the DIFF-01 migration ran
    and, for some reason, were never backfilled (should be rare/zero in
    practice since init_db() backfills on first migration, but surfaced
    honestly rather than silently treating them as id 0 or dropping them).
    """
    if not client_id:
        raise ValueError("client_id is required.")
    if limit <= 0 or limit > 1000:
        limit = 200
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                rows = conn.execute("""
                    SELECT row_id, date, category, amount, description, is_recurring
                    FROM ledgers
                    WHERE client_id = ?
                      AND (? IS NULL OR category = ?)
                      AND (? IS NULL OR strftime(TRY_CAST(date AS DATE), '%Y-%m') = ?)
                    ORDER BY TRY_CAST(date AS DATE) DESC
                    LIMIT ?
                """, [client_id, category, category, month, month, limit]).fetchall()
                result_rows = [
                    {
                        "row_id": r[0],
                        "date": r[1],
                        "category": r[2],
                        "amount": r[3],
                        "description": r[4],
                        "is_recurring": r[5],
                    }
                    for r in rows
                ]
                return {
                    "client_id": client_id,
                    "filter": {"category": category, "month": month},
                    "row_count": len(result_rows),
                    "legacy_row_count": sum(1 for r in result_rows if r["row_id"] is None),
                    "rows": result_rows,
                }
            except Exception as e:
                logger.error(f"Failed to fetch ledger row drill-down for tenant '{client_id}': {e}")
                raise
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


# DIFF-06: auto-categorization suggestions. Deterministic only, per founder
# decision (2026-08-23) -- a suggestion is derived from this SAME tenant's
# own already-categorized rows via keyword overlap, never an LLM guess and
# never auto-applied. A row's description is reduced to its significant
# words (lowercased, punctuation stripped, short/numeric tokens dropped),
# and matched against the same reduction of every OTHER already-categorized
# row for this tenant; the most common category among rows sharing at
# least one keyword becomes the suggestion, with a real confidence value
# (the fraction of keyword-matching rows that agree on that category) and
# the real match count backing it -- both shown to the user, never hidden.
_CATEGORY_SUGGESTION_STOPWORDS = {
    "the", "and", "for", "to", "of", "in", "on", "at", "a", "an", "with",
    "from", "inc", "llc", "co", "corp", "payment", "transaction", "purchase",
}


def _significant_words(text: str) -> set:
    words = "".join(c if c.isalnum() else " " for c in str(text).lower()).split()
    return {
        w for w in words
        if len(w) >= 3 and not w.isdigit() and w not in _CATEGORY_SUGGESTION_STOPWORDS
    }


def _suggest_category_for(description: str, categorized_rows: list) -> dict:
    """
    categorized_rows: list of (description, category) tuples for this
    tenant's rows that already have a real (non-"Uncategorized") category.
    Returns {"suggested_category": str|None, "confidence": float|None,
    "matched_row_count": int}. Pure function -- no DB access -- so this can
    be unit-tested directly without the DB/lock/thread-offload machinery.
    """
    target_words = _significant_words(description)
    if not target_words:
        return {"suggested_category": None, "confidence": None, "matched_row_count": 0}

    votes = {}
    total_matches = 0
    for other_desc, other_category in categorized_rows:
        if _significant_words(other_desc) & target_words:
            votes[other_category] = votes.get(other_category, 0) + 1
            total_matches += 1

    if not votes:
        return {"suggested_category": None, "confidence": None, "matched_row_count": 0}

    top_category, top_count = max(votes.items(), key=lambda kv: kv[1])
    return {
        "suggested_category": top_category,
        "confidence": round(top_count / total_matches, 3),
        "matched_row_count": total_matches,
    }


async def suggest_category_fixes(client_id: str) -> dict:
    """
    Returns a suggestion for every currently-"Uncategorized" row this
    tenant has, computed against their own other categorized rows. Never
    writes to the DB -- see apply_category_suggestion for that, which
    requires a real row_id (DIFF-01) so it can update the exact row the
    user confirmed, not a guess at which one they meant.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                uncategorized = conn.execute(
                    "SELECT row_id, description, amount, date FROM ledgers "
                    "WHERE client_id = ? AND category = 'Uncategorized'",
                    [client_id]
                ).fetchall()
                if not uncategorized:
                    return {"client_id": client_id, "suggestions": []}

                categorized_rows = conn.execute(
                    "SELECT description, category FROM ledgers "
                    "WHERE client_id = ? AND category != 'Uncategorized'",
                    [client_id]
                ).fetchall()

                suggestions = []
                for row_id, description, amount, txn_date in uncategorized:
                    result = _suggest_category_for(description, categorized_rows)
                    if result["suggested_category"] is not None:
                        suggestions.append({
                            "row_id": row_id,
                            "date": txn_date,
                            "description": description,
                            "amount": amount,
                            **result,
                        })
                return {"client_id": client_id, "suggestions": suggestions}
            except Exception as e:
                logger.error(f"Failed to compute category suggestions for tenant '{client_id}': {e}")
                raise
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


async def apply_category_suggestion(client_id: str, row_id: int, new_category: str) -> bool:
    """
    Applies ONE user-confirmed category to ONE specific row, targeted by
    its real row_id (DIFF-01) -- never a bulk/heuristic update, and never
    called automatically; the frontend only calls this after the user
    explicitly accepts a specific suggestion. row_id IS NOT NULL is
    required in the WHERE clause on purpose: a legacy row with no row_id
    (pre-DIFF-01 data that somehow missed the backfill) cannot be safely
    targeted this way and must be re-uploaded instead. Returns True if a
    row was actually updated, False if no matching row was found (wrong
    row_id, wrong tenant, or a legacy NULL row_id) -- the caller can use
    this to distinguish a real update from a silent no-op.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    if row_id is None:
        raise ValueError("row_id is required.")
    if not new_category or not str(new_category).strip():
        raise ValueError("new_category is required.")
    lock = get_db_lock()
    def _update():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute(
                    "UPDATE ledgers SET category = ? "
                    "WHERE client_id = ? AND row_id = ? AND row_id IS NOT NULL",
                    [str(new_category).strip(), client_id, row_id]
                )
                updated = conn.execute(
                    "SELECT category FROM ledgers WHERE client_id = ? AND row_id = ?",
                    [client_id, row_id]
                ).fetchone()
                return updated is not None and updated[0] == str(new_category).strip()
            except Exception as e:
                logger.error(f"Failed to apply category suggestion for tenant '{client_id}' row {row_id}: {e}")
                raise
            finally:
                conn.close()
    return await asyncio.to_thread(_update)
```

Everything else in `db_manager.py` — ingestion parsing, `get_ledger_chart_context`, `get_forecast_accuracy`, telemetry logging, tenant deletion, and every other pre-existing function — is unchanged.

### Frontend — New Components

#### `frontend/components/AssumptionLedger.tsx`

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { BookOpenCheck, Loader2, AlertCircle } from "lucide-react";
import { useClientId } from "./ClientContext";

// DIFF-02: Assumption ledger. Renders the REAL numeric constants and
// methodology notes returned by GET /api/v1/assumptions -- nothing here
// is hardcoded; every value comes straight from the backend's live
// module constants (see backend/assumptions.py), so this can never drift
// out of sync with the code actually computing CFO/forecast figures.
interface NumericAssumption {
  key: string;
  label: string;
  value: number;
  unit: string;
  used_by: string;
  description: string;
}

interface MethodologyNote {
  key: string;
  label: string;
  used_by: string;
  description: string;
}

interface AssumptionsResponse {
  numeric_assumptions: NumericAssumption[];
  methodology_notes: MethodologyNote[];
}

function formatValue(value: number, unit: string): string {
  if (unit === "usd") {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
  }
  if (unit === "% per month") {
    return `${value}%/mo`;
  }
  return `${value} ${unit}`;
}

export default function AssumptionLedger() {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [data, setData] = useState<AssumptionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAssumptions = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const response = await fetch(`${backendUrl}/api/v1/assumptions`, {
        method: "GET",
        headers: {
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        signal,
      });
      if (!response.ok) {
        throw new Error(`Assumption ledger request failed: ${response.status}`);
      }
      setData(await response.json());
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Assumption ledger fetch failed:", err);
      setError(err.message || "Assumption ledger is currently unavailable.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [authToken, authReady]);

  useEffect(() => {
    const controller = new AbortController();
    fetchAssumptions(controller.signal);
    return () => controller.abort();
  }, [fetchAssumptions]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-amber-500/10 border border-amber-500/20 rounded-lg">
          <BookOpenCheck className="w-5 h-5 text-amber-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Assumption Ledger</h2>
          <p className="text-xs text-slate-400">Every constant and methodology choice your numbers above actually depend on</p>
        </div>
      </div>

      <div className="p-6 flex-1">
        {error && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-amber-400">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Loading assumption ledger...</p>
          </div>
        ) : (
          <div className="space-y-6 animate-in fade-in duration-500">
            <div>
              <h3 className="text-sm font-semibold text-slate-300 mb-3">Numeric Assumptions</h3>
              <div className="overflow-x-auto rounded-lg border border-slate-800">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-950/50 text-left text-xs uppercase tracking-wider text-slate-500">
                      <th className="px-4 py-2.5 font-semibold">Assumption</th>
                      <th className="px-4 py-2.5 font-semibold">Value</th>
                      <th className="px-4 py-2.5 font-semibold">Used By</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.numeric_assumptions ?? []).map((row) => (
                      <tr key={row.key} className="border-t border-slate-800/70 align-top">
                        <td className="px-4 py-3">
                          <p className="text-slate-200 font-medium">{row.label}</p>
                          <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{row.description}</p>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-amber-400 font-semibold">
                          {formatValue(row.value, row.unit)}
                        </td>
                        <td className="px-4 py-3 text-slate-400">{row.used_by}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-slate-300 mb-3">Methodology Notes</h3>
              <div className="space-y-3">
                {(data?.methodology_notes ?? []).map((note) => (
                  <div key={note.key} className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-3.5">
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <p className="text-sm font-medium text-slate-200">{note.label}</p>
                      <span className="text-xs text-slate-500 whitespace-nowrap">{note.used_by}</span>
                    </div>
                    <p className="text-xs text-slate-400 leading-relaxed">{note.description}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

#### `frontend/components/KnownGapsPanel.tsx`

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { HelpCircle, Loader2, AlertCircle, Info } from "lucide-react";
import { useClientId } from "./ClientContext";

// DIFF-03: "What I don't know yet" panel. Every entry rendered here comes
// straight from POST /api/v1/insights/known-gaps -- a real, currently-true
// limitation for this tenant (see backend/gaps.py), never a placeholder or
// invented caveat. Trust-building by being upfront about real gaps rather
// than only showing what works.
interface Gap {
  key: string;
  title: string;
  detail: string;
}

interface KnownGapsResponse {
  client_id: string;
  row_count: number;
  gaps: Gap[];
}

interface KnownGapsPanelProps {
  refreshTrigger?: number;
}

export default function KnownGapsPanel({ refreshTrigger = 0 }: KnownGapsPanelProps) {
  const clientCtx = useClientId() as any;
  const currentClientId = clientCtx?.clientId || "CLI-001";
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [data, setData] = useState<KnownGapsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchGaps = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const response = await fetch(`${backendUrl}/api/v1/insights/known-gaps`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        signal,
      });
      if (!response.ok) {
        throw new Error(`Known-gaps request failed: ${response.status}`);
      }
      setData(await response.json());
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Known-gaps fetch failed:", err);
      setError(err.message || "Unable to load known limitations right now.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [currentClientId, authToken, authReady]);

  useEffect(() => {
    const controller = new AbortController();
    fetchGaps(controller.signal);
    return () => controller.abort();
  }, [fetchGaps, refreshTrigger]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-sky-500/10 border border-sky-500/20 rounded-lg">
          <HelpCircle className="w-5 h-5 text-sky-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">What NexusFlow Doesn't Know Yet</h2>
          <p className="text-xs text-slate-400">Real, current limitations for this tenant -- not a hedge, an actual list</p>
        </div>
      </div>

      <div className="p-6 flex-1">
        {error && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-sky-400">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Checking current data coverage...</p>
          </div>
        ) : data && data.gaps.length === 0 ? (
          <div className="flex items-center gap-3 text-emerald-400 py-4">
            <Info className="w-5 h-5 shrink-0" />
            <p className="text-sm">No known gaps for this tenant right now.</p>
          </div>
        ) : (
          <div className="space-y-3 animate-in fade-in duration-500">
            {(data?.gaps ?? []).map((gap) => (
              <div key={gap.key} className="flex gap-3 items-start bg-slate-800/30 p-3.5 rounded-lg border border-slate-700/30">
                <Info className="w-4 h-4 text-sky-400 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-slate-200">{gap.title}</p>
                  <p className="text-xs text-slate-400 mt-1 leading-relaxed">{gap.detail}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

#### `frontend/components/LedgerRowExplorer.tsx`

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { Search, Loader2, AlertCircle, ListFilter } from "lucide-react";
import { useClientId } from "./ClientContext";

// DIFF-01: evidence trail. Real drill-down into the exact ledger rows
// behind a category/month via POST /api/v1/finance/ledger-rows -- every
// row shown here carries its real row_id (see backend/db_manager.py's
// DIFF-01 migration), not a fabricated reference. Scope note: this is a
// standalone explorer, not (yet) wired into every chart/insight elsewhere
// on the dashboard as a click-through -- see backend/evidence.py's module
// docstring for why that's a separate, larger step.
interface LedgerRow {
  row_id: number | null;
  date: string;
  category: string;
  amount: number;
  description: string;
  is_recurring: boolean | null;
}

interface LedgerRowsResponse {
  client_id: string;
  filter: { category: string | null; month: string | null };
  row_count: number;
  legacy_row_count: number;
  rows: LedgerRow[];
}

interface LedgerRowExplorerProps {
  refreshTrigger?: number;
}

export default function LedgerRowExplorer({ refreshTrigger = 0 }: LedgerRowExplorerProps) {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [category, setCategory] = useState("");
  const [month, setMonth] = useState("");
  const [data, setData] = useState<LedgerRowsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRows = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const response = await fetch(`${backendUrl}/api/v1/finance/ledger-rows`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          category: category.trim() || null,
          month: month.trim() || null,
          limit: 50,
        }),
        signal,
      });
      if (!response.ok) {
        throw new Error(`Ledger row lookup failed: ${response.status}`);
      }
      setData(await response.json());
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Ledger row explorer fetch failed:", err);
      setError(err.message || "Unable to load ledger rows right now.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [authToken, authReady, category, month]);

  useEffect(() => {
    const controller = new AbortController();
    fetchRows(controller.signal);
    return () => controller.abort();
  }, [fetchRows, refreshTrigger]);

  const formatCurrency = (n: number) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-violet-500/10 border border-violet-500/20 rounded-lg">
            <Search className="w-5 h-5 text-violet-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">Ledger Row Explorer</h2>
            <p className="text-xs text-slate-400">See the exact transactions behind any category or month</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="Category (exact)"
            className="text-xs bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200 placeholder:text-slate-500 w-36"
          />
          <input
            type="text"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            placeholder="YYYY-MM"
            className="text-xs bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200 placeholder:text-slate-500 w-24"
          />
          <button
            onClick={() => fetchRows()}
            disabled={loading}
            className="text-xs bg-violet-600/20 hover:bg-violet-600/30 text-violet-300 px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors disabled:opacity-50 border border-violet-700/40"
          >
            <ListFilter className="w-3 h-3" />
            Filter
          </button>
        </div>
      </div>

      <div className="p-6 flex-1">
        {error && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !data ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-violet-400">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Loading rows...</p>
          </div>
        ) : data && data.row_count === 0 ? (
          <p className="text-sm text-slate-500 italic py-4">No matching rows.</p>
        ) : (
          <div className="animate-in fade-in duration-500">
            {data && data.legacy_row_count > 0 && (
              <p className="text-xs text-amber-400/80 mb-3">
                {data.legacy_row_count} of these rows predate row-level tracking and have no stable id yet -- re-upload to assign one.
              </p>
            )}
            <div className="overflow-x-auto rounded-lg border border-slate-800">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-950/50 text-left text-xs uppercase tracking-wider text-slate-500">
                    <th className="px-4 py-2.5 font-semibold">Date</th>
                    <th className="px-4 py-2.5 font-semibold">Category</th>
                    <th className="px-4 py-2.5 font-semibold">Description</th>
                    <th className="px-4 py-2.5 font-semibold text-right">Amount</th>
                    <th className="px-4 py-2.5 font-semibold">Row ID</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.rows ?? []).map((row, idx) => (
                    <tr key={row.row_id ?? idx} className="border-t border-slate-800/70">
                      <td className="px-4 py-2.5 text-slate-300 whitespace-nowrap">{row.date}</td>
                      <td className="px-4 py-2.5 text-slate-300">{row.category}</td>
                      <td className="px-4 py-2.5 text-slate-400">{row.description}</td>
                      <td className={`px-4 py-2.5 text-right font-medium whitespace-nowrap ${row.amount >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {formatCurrency(row.amount)}
                      </td>
                      <td className="px-4 py-2.5 text-slate-500 text-xs">{row.row_id ?? "legacy"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

#### `frontend/components/CategorySuggestionsWidget.tsx`

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { Sparkles, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";
import { useClientId } from "./ClientContext";

// DIFF-06: deterministic auto-categorization suggestions. Every suggestion
// is derived purely from this tenant's own already-categorized rows via
// real keyword overlap (see backend/db_manager.py's _suggest_category_for)
// -- never an LLM guess, and never applied without an explicit click here.
// See backend/categorization.py's module docstring for the founder
// decision behind "deterministic only" (2026-08-23).
interface CategorySuggestion {
  row_id: number;
  description: string;
  date: string;
  amount: number;
  suggested_category: string;
  confidence: number;
  matched_row_count: number;
}

interface CategorySuggestionsResponse {
  client_id: string;
  suggestions: CategorySuggestion[];
}

interface CategorySuggestionsWidgetProps {
  refreshTrigger?: number;
  onApplied?: () => void;
}

export default function CategorySuggestionsWidget({ refreshTrigger = 0, onApplied }: CategorySuggestionsWidgetProps) {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [suggestions, setSuggestions] = useState<CategorySuggestion[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [applyingRowId, setApplyingRowId] = useState<number | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  const fetchSuggestions = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${backendUrl}/api/v1/data/category-suggestions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({}),
        signal,
      });
      if (!response.ok) {
        throw new Error(`Category suggestions lookup failed: ${response.status}`);
      }
      const json: CategorySuggestionsResponse = await response.json();
      setSuggestions(json.suggestions ?? []);
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Category suggestions fetch failed:", err);
      setError(err.message || "Unable to load category suggestions right now.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [authToken, authReady, backendUrl]);

  useEffect(() => {
    const controller = new AbortController();
    fetchSuggestions(controller.signal);
    return () => controller.abort();
  }, [fetchSuggestions, refreshTrigger]);

  const applySuggestion = async (rowId: number, newCategory: string) => {
    setApplyingRowId(rowId);
    setApplyError(null);
    try {
      const response = await fetch(`${backendUrl}/api/v1/data/apply-category-suggestion`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ row_id: rowId, new_category: newCategory }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `Apply failed: ${response.status}`);
      }
      setSuggestions((prev) => (prev ? prev.filter((s) => s.row_id !== rowId) : prev));
      onApplied?.();
    } catch (err: any) {
      console.error("Apply category suggestion failed:", err);
      setApplyError(err.message || "Unable to apply this suggestion right now.");
    } finally {
      setApplyingRowId(null);
    }
  };

  const formatCurrency = (n: number) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-fuchsia-500/10 border border-fuchsia-500/20 rounded-lg">
          <Sparkles className="w-5 h-5 text-fuchsia-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Category Suggestions</h2>
          <p className="text-xs text-slate-400">Deterministic matches from your own categorized rows -- never applied automatically</p>
        </div>
      </div>

      <div className="p-6 flex-1">
        {error ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !suggestions ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-fuchsia-400">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Looking for suggestions...</p>
          </div>
        ) : suggestions && suggestions.length === 0 ? (
          <p className="text-sm text-slate-500 italic py-4">No suggestions right now -- either everything's categorized or nothing matches closely enough.</p>
        ) : (
          <div className="space-y-3 animate-in fade-in duration-500">
            {applyError && (
              <p className="text-xs text-rose-400/90 mb-1">{applyError}</p>
            )}
            {(suggestions ?? []).map((s) => (
              <div key={s.row_id} className="border border-slate-800 rounded-lg p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm text-slate-200 truncate">{s.description}</p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {s.date} &middot; {formatCurrency(s.amount)}
                  </p>
                  <p className="text-xs text-slate-400 mt-1">
                    Suggested: <span className="text-fuchsia-300 font-medium">{s.suggested_category}</span>
                    <span className="text-slate-600"> &middot; </span>
                    {Math.round(s.confidence * 100)}% confidence
                    <span className="text-slate-600"> &middot; </span>
                    {s.matched_row_count} matching row{s.matched_row_count === 1 ? "" : "s"}
                  </p>
                </div>
                <button
                  onClick={() => applySuggestion(s.row_id, s.suggested_category)}
                  disabled={applyingRowId === s.row_id}
                  className="text-xs bg-fuchsia-600/20 hover:bg-fuchsia-600/30 text-fuchsia-300 px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors disabled:opacity-50 border border-fuchsia-700/40 shrink-0"
                >
                  {applyingRowId === s.row_id ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <CheckCircle2 className="w-3 h-3" />
                  )}
                  Accept
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

#### `frontend/components/OnboardingChecklist.tsx`

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { ListChecks, Loader2, AlertCircle, CheckCircle2, Circle, Lock } from "lucide-react";
import { useClientId } from "./ClientContext";

// DIFF-05: lightweight first-insight onboarding checklist. Per founder
// decision (2026-08-23), this is a progress checklist, not a full guided
// modal tour -- pure frontend, reusing two endpoints that already exist
// (/api/v1/finance/kpi-summary and /api/v1/insights/known-gaps) rather than
// adding a new one. Every checklist item's status is derived from real
// signals already computed elsewhere, never a fabricated "you did this"
// flag.
interface KpiSummary {
  ledger_row_count: number;
}

interface KnownGap {
  key: string;
  title: string;
  detail: string;
}

interface KnownGapsResponse {
  row_count: number;
  gaps: KnownGap[];
}

type ItemStatus = "done" | "available" | "locked";

interface ChecklistItem {
  key: string;
  title: string;
  detail: string;
  status: ItemStatus;
}

interface OnboardingChecklistProps {
  refreshTrigger?: number;
}

export default function OnboardingChecklist({ refreshTrigger = 0 }: OnboardingChecklistProps) {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [items, setItems] = useState<ChecklistItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProgress = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const headers = {
        "Content-Type": "application/json",
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      };
      const [kpiRes, gapsRes] = await Promise.all([
        fetch(`${backendUrl}/api/v1/finance/kpi-summary`, { method: "POST", headers, body: JSON.stringify({}), signal }),
        fetch(`${backendUrl}/api/v1/insights/known-gaps`, { method: "POST", headers, body: JSON.stringify({}), signal }),
      ]);
      if (!kpiRes.ok) throw new Error(`KPI summary lookup failed: ${kpiRes.status}`);
      if (!gapsRes.ok) throw new Error(`Known gaps lookup failed: ${gapsRes.status}`);

      const kpi: KpiSummary = await kpiRes.json();
      const gapsData: KnownGapsResponse = await gapsRes.json();
      const gapKeys = new Set(gapsData.gaps.map((g) => g.key));

      const hasData = (kpi.ledger_row_count ?? 0) > 0;
      const mrrUnlocked = hasData && !gapKeys.has("mrr_unavailable");
      const forecastUnlocked = hasData && !gapKeys.has("forecast_insufficient_history");

      const built: ChecklistItem[] = [
        {
          key: "upload_data",
          title: "Upload your ledger data",
          detail: hasData
            ? `${kpi.ledger_row_count} row(s) on file.`
            : "Upload a CSV to unlock CFO briefings, forecasts, and the rest of this dashboard.",
          status: hasData ? "done" : "available",
        },
        {
          key: "mrr",
          title: "Unlock real Monthly Recurring Revenue",
          detail: mrrUnlocked
            ? "MRR is being tracked from your recurring-flagged rows."
            : "Include a 'recurring' or 'is_recurring' column on your next upload to unlock true MRR.",
          status: !hasData ? "locked" : mrrUnlocked ? "done" : "available",
        },
        {
          key: "forecast",
          title: "Unlock 12-month forecasting",
          detail: forecastUnlocked
            ? "You have enough monthly history for statistically meaningful forecasts."
            : "Keep uploading -- forecasting unlocks once enough distinct months of history are on file.",
          status: !hasData ? "locked" : forecastUnlocked ? "done" : "available",
        },
      ];
      setItems(built);
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Onboarding checklist fetch failed:", err);
      setError(err.message || "Unable to load onboarding progress right now.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [authToken, authReady]);

  useEffect(() => {
    const controller = new AbortController();
    fetchProgress(controller.signal);
    return () => controller.abort();
  }, [fetchProgress, refreshTrigger]);

  const doneCount = (items ?? []).filter((i) => i.status === "done").length;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
            <ListChecks className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">Getting Started</h2>
            <p className="text-xs text-slate-400">Your progress unlocking NexusFlow's analysis</p>
          </div>
        </div>
        {items && (
          <span className="text-xs font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-full px-2.5 py-1 shrink-0">
            {doneCount}/{items.length}
          </span>
        )}
      </div>

      <div className="p-6 flex-1">
        {error ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !items ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-emerald-400">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Checking your progress...</p>
          </div>
        ) : (
          <ul className="space-y-3 animate-in fade-in duration-500">
            {(items ?? []).map((item) => (
              <li key={item.key} className="flex items-start gap-3">
                {item.status === "done" ? (
                  <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
                ) : item.status === "locked" ? (
                  <Lock className="w-5 h-5 text-slate-600 shrink-0 mt-0.5" />
                ) : (
                  <Circle className="w-5 h-5 text-slate-500 shrink-0 mt-0.5" />
                )}
                <div className="min-w-0">
                  <p className={`text-sm font-medium ${item.status === "done" ? "text-slate-300 line-through decoration-slate-600" : item.status === "locked" ? "text-slate-500" : "text-slate-200"}`}>
                    {item.title}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">{item.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
```

### Frontend — `frontend/app/page.tsx` (full current file)

```tsx
'use client';

import { useState, useEffect } from 'react';
import { Cpu, Server, ShieldCheck } from 'lucide-react';
import SubAgentWidget from '../components/SubAgentWidget';
import SwarmLogStreamer from '../components/SwarmLogStreamer';
import { ClientProvider } from '../components/ClientContext'; 
import CognitiveSearchBar from '../components/CognitiveSearchBar';
import AdvancedAnalyticsDashboard from '../components/AdvancedAnalyticsDashboard';
import VirtualCFOWidget from '../components/VirtualCFOWidget';
import DataEngineerWidget from '../components/DataEngineerWidget';
import ETLDropzone from '../components/ETLDropzone';
import { SwarmVisualizer } from '../components/SwarmVisualizer';
import KpiGrid from '../components/KpiGrid';
import DataVisualizationWidget from '../components/DataVisualizationWidget';
import KnownGapsPanel from '../components/KnownGapsPanel';
import AssumptionLedger from '../components/AssumptionLedger';
import OnboardingChecklist from '../components/OnboardingChecklist';
import CategorySuggestionsWidget from '../components/CategorySuggestionsWidget';
import LedgerRowExplorer from '../components/LedgerRowExplorer';

interface HealthData {
  status: string;
  docker_detected: boolean;
  active_agent_modules: number;
  version: string;
}

interface SearchResult {
  query: string;
  synthesized_insight: string;
  agent_breakdown: Array<{
    agent_name: string;
    domain: string;
    output_summary: string;
    raw_artifacts?: unknown;
  }>;
  confidence_score: number;
  status: string;
}

export default function CoreDashboard() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [dashboardRefreshTrigger, setDashboardRefreshTrigger] = useState<number>(0);

  useEffect(() => {
    async function fetchHealth() {
      try {
        const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
        const res = await fetch(`${backendUrl}/api/v1/health`);
        
        if (!res.ok) {
          throw new Error(`Health check failed: ${res.status}`);
        }

        const data: HealthData = await res.json();
        setHealth(data);
      } catch (err) {
        console.error("Health check failed:", err);
      } finally {
        setLoading(false);
      }
    }
    fetchHealth();
  }, []);

  return (
    <ClientProvider>
      <div className="min-h-screen bg-slate-950 text-slate-100 font-sans p-6 md:p-12 space-y-8">
        
        {/* Header */}
        <header className="flex justify-between items-center pb-8 border-b border-slate-800">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              <Cpu className="text-indigo-500 w-7 h-7" />
              NexusFlow Analytics
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Enterprise AI Systems & Business Intelligence Gateway
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${
              health 
                ? 'bg-emerald-950 text-emerald-400 border-emerald-800' 
                : 'bg-slate-900 text-slate-400 border-slate-800'
            }`}>
              <span className={`w-2 h-2 rounded-full ${health ? 'bg-emerald-500 animate-pulse' : 'bg-slate-500'}`}></span>
              {health ? 'Supervisor Online' : 'Supervisor Offline'}
            </span>
          </div>
        </header>

        {/* DIFF-05: lightweight onboarding progress checklist -- pure
            frontend, derived from real signals already exposed by
            kpi-summary and known-gaps (no new backend endpoint). */}
        <section><OnboardingChecklist refreshTrigger={dashboardRefreshTrigger} /></section>

        {/* Top Metrics Cards */}
        <main className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">System State</span>
              <Server className="w-5 h-5 text-indigo-400" />
            </div>
            <div className="mt-4">
              <p className="text-2xl font-bold text-white">{loading ? "Checking..." : health?.status || "OFFLINE"}</p>
              <p className="text-xs text-slate-500 mt-1">FastAPI Engine v{health?.version || "1.0.0"}</p>
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Runtime Security</span>
              <ShieldCheck className="w-5 h-5 text-emerald-400" />
            </div>
            <div className="mt-4">
              <p className="text-2xl font-bold text-white">
                {loading
                  ? "CHECKING"
                  : health === null
                    ? "OFFLINE"
                    : health.docker_detected
                      ? "ISOLATED"
                      : "UNSECURED"}
              </p>
              <p className="text-xs text-slate-500 mt-1">RevSecOps & SysAdmin Policy Enforced</p>
            </div>
          </div>

          <SubAgentWidget />
        </main>

        <section><CognitiveSearchBar onQueryResult={(data) => setSearchResult(data)} /></section>
        
        <section><KpiGrid refreshTrigger={dashboardRefreshTrigger} /></section>
        
        <section><SwarmLogStreamer sessionId="active_dashboard_session" /></section>

        {searchResult && (
          <section className="animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
            <SwarmVisualizer data={searchResult} />
          </section>
        )}

        <section><AdvancedAnalyticsDashboard refreshTrigger={dashboardRefreshTrigger} /></section>

        <section><DataVisualizationWidget refreshTrigger={dashboardRefreshTrigger} /></section>

        {/* Financial & Data Engineering Intelligence Grid */}
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <VirtualCFOWidget refreshTrigger={dashboardRefreshTrigger} />
          <DataEngineerWidget refreshTrigger={dashboardRefreshTrigger} />
        </section>

        {/* DIFF-03 / DIFF-02: transparency pair -- what NexusFlow doesn't
            know yet for this tenant, and the real constants/methodology
            every calculation above depends on. */}
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <KnownGapsPanel refreshTrigger={dashboardRefreshTrigger} />
          <AssumptionLedger />
        </section>

        {/* DIFF-06 / DIFF-01: deterministic category suggestions (accept
            applies a real row_id-targeted update) paired with the evidence-
            trail row explorer they both rely on. */}
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <CategorySuggestionsWidget
            refreshTrigger={dashboardRefreshTrigger}
            onApplied={() => setDashboardRefreshTrigger(prev => prev + 1)}
          />
          <LedgerRowExplorer refreshTrigger={dashboardRefreshTrigger} />
        </section>

        {/* Automated Data Ingestion Section */}
        <section>
          <ETLDropzone onUploadSuccess={() => setDashboardRefreshTrigger(prev => prev + 1)} />
        </section>

      </div>
    </ClientProvider>
  );
}
```

---

## Part 3 — Documentation Updated This Session

Five project documents were also updated to reflect all of the above (`docs/` folder in the repo):

- `NexusFlow_Master_Build_List_v1.7.docx` — full status/backlog record.
- `NexusFlow_Executive_Summary_v1.1.docx`
- `NexusFlow_SRS_v2.1_Production_Requirements.docx`
- `NexusFlow_SaaS_Lifecycle_Executive_Manual.docx`
- `NexusFlow_Source_of_Truth.docx`

See the companion handoff document for what's next (Phases 5–8).
