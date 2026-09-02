"""
Real (non-stub) tests for SQL-03: per-user attribution on the query_audit
trail. Before this file, NOTHING in backend/tests/ exercised query_audit,
_answer_data_question, or generate_bi_summary at all (confirmed via grep
before writing this file) -- this is genuinely new coverage, not a rewrite
of existing tests.

Three things are proven here, each against real code (no business logic
mocked, only the OpenAI network boundary where a test needs it):

1. `log_query_audit` (db_manager.py) actually persists a given `user_id`
   into a real row, round-tripped through a real DuckDB file -- and
   defaults to NULL when the caller omits it, so existing/tenant-only
   callers keep working unchanged.

2. The lazy migration guard: a `query_audit` table created BEFORE this
   change (the old 6-column shape, no `user_id`) gets the column added on
   the next write rather than erroring -- the same real-world situation an
   already-deployed tenant's database is in the moment this ships. Uses
   the same PRAGMA table_info()-based existence check as AUTH-06's
   device_label/session_started_at precedent, verified directly against
   the real column list (not assumed).

3. `_answer_data_question` (bi_engineer.py) threads a passed-in `user_id`
   all the way into the audit row on the LLM_UNAVAILABLE_OR_FAILED branch
   -- the one AI-dependent branch this suite can exercise for real without
   a live OpenAI key, matching this codebase's own established convention
   for testing AI-adjacent code paths (see test_orchestrator_integration.py
   Layer 2, which relies on the same "no OpenAI client gets built" shape).
"""
import duckdb
import pytest


# ---------------------------------------------------------------------------
# 1. log_query_audit: user_id persists correctly; defaults to NULL.
# ---------------------------------------------------------------------------

def _read_query_audit_rows(db_path):
    conn = duckdb.connect(db_path, read_only=True)
    try:
        return conn.execute(
            "SELECT client_id, natural_language_query, generated_query, "
            "row_count, status, user_id FROM query_audit ORDER BY audit_id"
        ).fetchall()
    finally:
        conn.close()


def test_log_query_audit_persists_given_user_id(isolated_db):
    import asyncio

    asyncio.run(isolated_db.log_query_audit(
        "CLI-AUDIT-TEST", "what is our revenue?", "SELECT SUM(amount) ...", 1, "SUCCESS", user_id=42,
    ))

    rows = _read_query_audit_rows(isolated_db.DB_PATH)
    assert len(rows) == 1
    client_id, nl_query, gen_query, row_count, status, user_id = rows[0]
    assert client_id == "CLI-AUDIT-TEST"
    assert nl_query == "what is our revenue?"
    assert row_count == 1
    assert status == "SUCCESS"
    assert user_id == 42


def test_log_query_audit_defaults_user_id_to_null_when_omitted(isolated_db):
    import asyncio

    # No user_id passed at all -- must not raise, and must store NULL, not
    # some sentinel value or a crash from a missing required argument.
    asyncio.run(isolated_db.log_query_audit(
        "CLI-AUDIT-TEST-2", "what is our revenue?", "SELECT SUM(amount) ...", 1, "SUCCESS",
    ))

    rows = _read_query_audit_rows(isolated_db.DB_PATH)
    assert len(rows) == 1
    assert rows[0][5] is None


def test_log_query_audit_explicit_none_also_stores_null(isolated_db):
    import asyncio

    asyncio.run(isolated_db.log_query_audit(
        "CLI-AUDIT-TEST-3", "q", "N/A", 0, "LLM_UNAVAILABLE_OR_FAILED", user_id=None,
    ))

    rows = _read_query_audit_rows(isolated_db.DB_PATH)
    assert rows[0][5] is None


# ---------------------------------------------------------------------------
# 2. Migration guard: a pre-existing, old-shape query_audit table (no
#    user_id column) gets the column added on the next write, not an error.
# ---------------------------------------------------------------------------

def test_log_query_audit_migrates_pre_existing_table_missing_user_id_column(isolated_db):
    import asyncio

    # Build the OLD-shape table by hand -- exactly what a real tenant's
    # database looks like today, before this change ever ran against it.
    conn = duckdb.connect(isolated_db.DB_PATH)
    try:
        conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS query_audit_id_seq;
            CREATE TABLE query_audit (
                audit_id BIGINT DEFAULT nextval('query_audit_id_seq'),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                client_id VARCHAR,
                natural_language_query VARCHAR,
                generated_query VARCHAR,
                row_count INTEGER,
                status VARCHAR
            )
        """)
        # A pre-existing row, written before this migration ever ran --
        # must survive the ALTER TABLE untouched (backfills to NULL, not
        # dropped or corrupted).
        conn.execute(
            "INSERT INTO query_audit (client_id, natural_language_query, generated_query, row_count, status) "
            "VALUES (?, ?, ?, ?, ?)",
            ["CLI-PRE-EXISTING", "old question", "SELECT 1", 0, "SUCCESS"],
        )
    finally:
        conn.close()

    cols_before = [r[1] for r in duckdb.connect(isolated_db.DB_PATH, read_only=True)
                   .execute("PRAGMA table_info('query_audit')").fetchall()]
    assert "user_id" not in cols_before

    # The next write must trigger the migration guard, not raise.
    asyncio.run(isolated_db.log_query_audit(
        "CLI-NEW", "new question", "SELECT 2", 1, "SUCCESS", user_id=7,
    ))

    cols_after = [r[1] for r in duckdb.connect(isolated_db.DB_PATH, read_only=True)
                  .execute("PRAGMA table_info('query_audit')").fetchall()]
    assert "user_id" in cols_after

    rows = _read_query_audit_rows(isolated_db.DB_PATH)
    assert len(rows) == 2
    # The pre-existing row backfills to NULL user_id, not dropped or errored.
    pre_existing = next(r for r in rows if r[0] == "CLI-PRE-EXISTING")
    assert pre_existing[5] is None
    # The new row correctly stores the user_id passed at write time.
    new_row = next(r for r in rows if r[0] == "CLI-NEW")
    assert new_row[5] == 7


def test_log_query_audit_migration_guard_is_idempotent_across_repeated_writes(isolated_db):
    """The PRAGMA table_info()-based existence check (mirrors AUTH-06's
    device_label/session_started_at pattern) must not error or duplicate
    the column on a second write once user_id already exists."""
    import asyncio

    asyncio.run(isolated_db.log_query_audit("CLI-A", "q1", "sql1", 0, "SUCCESS", user_id=1))
    asyncio.run(isolated_db.log_query_audit("CLI-B", "q2", "sql2", 0, "SUCCESS", user_id=2))

    rows = _read_query_audit_rows(isolated_db.DB_PATH)
    assert len(rows) == 2
    assert {r[5] for r in rows} == {1, 2}


# ---------------------------------------------------------------------------
# 3. _answer_data_question threads user_id into the audit row for real, on
#    the LLM_UNAVAILABLE_OR_FAILED branch (no live OpenAI key configured in
#    this suite -- see conftest.py's OPENAI_API_KEY placeholder comment).
# ---------------------------------------------------------------------------

def test_answer_data_question_threads_user_id_into_audit_row_on_llm_unavailable(isolated_db, monkeypatch):
    from backend.agents import bi_engineer

    # Force the LLM_UNAVAILABLE_OR_FAILED branch deterministically, rather
    # than relying on the placeholder OPENAI_API_KEY happening to fail in
    # a way that lands here -- same spirit as test_orchestrator_integration
    # .py's monkeypatched OpenAI boundary, just returning None instead of a
    # stub client.
    monkeypatch.setattr(bi_engineer, "_ask_llm_for_query_intent", lambda client_id, query: None)

    result = bi_engineer._answer_data_question("CLI-BI-AUDIT", "what are our top categories?", user_id=99)

    assert result["status"] == "COULD_NOT_ANSWER"

    rows = _read_query_audit_rows(isolated_db.DB_PATH)
    assert len(rows) == 1
    client_id, nl_query, gen_query, row_count, status, user_id = rows[0]
    assert client_id == "CLI-BI-AUDIT"
    assert status == "LLM_UNAVAILABLE_OR_FAILED"
    assert user_id == 99


def test_answer_data_question_user_id_defaults_to_none_when_not_passed(isolated_db, monkeypatch):
    from backend.agents import bi_engineer

    monkeypatch.setattr(bi_engineer, "_ask_llm_for_query_intent", lambda client_id, query: None)

    # Caller doesn't know the user (e.g. a tooling script) -- must not
    # raise, and the audit row's user_id must be NULL, exactly as it was
    # before SQL-03 added this parameter.
    result = bi_engineer._answer_data_question("CLI-BI-AUDIT-2", "what are our top categories?")
    assert result["status"] == "COULD_NOT_ANSWER"

    rows = _read_query_audit_rows(isolated_db.DB_PATH)
    assert rows[0][5] is None


def test_answer_data_question_rejected_by_whitelist_branch_threads_user_id(isolated_db, monkeypatch):
    """Same threading proof, on the REJECTED_BY_WHITELIST branch -- a raw
    intent that fails _validate_intent (e.g. an unrecognized mode)."""
    from backend.agents import bi_engineer

    monkeypatch.setattr(
        bi_engineer, "_ask_llm_for_query_intent",
        lambda client_id, query: {"mode": "not-a-real-mode"},
    )

    result = bi_engineer._answer_data_question("CLI-BI-AUDIT-3", "a nonsense query", user_id=13)
    assert result["status"] == "COULD_NOT_ANSWER"

    rows = _read_query_audit_rows(isolated_db.DB_PATH)
    assert rows[0][4] == "REJECTED_BY_WHITELIST"
    assert rows[0][5] == 13
