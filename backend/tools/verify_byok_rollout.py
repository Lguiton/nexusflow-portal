"""
BYOK-01 rollout verification: a standalone, non-pytest script (same
convention as verify_mcp_server.py and model_regression_check.py) that
proves -- with real imports and a real isolated DuckDB, not mocked
business logic -- that all 8 previously-non-BYOK-aware agent modules
(virtual_cfo, bi_engineer, predictive_forecaster, report_generator,
saas_strategist, data_engineer, bi_visualization_architect,
external_telemetry_scout) now route every OpenAI call through
get_openai_client_for_tenant_sync(client_id, ...) with the CALLING
tenant's own client_id, instead of a module-level singleton client built
once from the platform's key at import time.

Two independent checks:

  SECTION A -- call-site wiring. For each of the 9 real call sites across
  the 8 modules, get_openai_client_for_tenant_sync is monkeypatched with a
  spy (returning a stub client whose .chat.completions.create() raises a
  recognizable sentinel, which the real function's own try/except turns
  into its ordinary error-state response -- the *business* JSON returned
  is irrelevant here). What's asserted is real: the spy's first positional
  arg was the exact client_id string this script called the function
  with, proving that value flows from the public function's own
  parameter, not a hardcoded id or the wrong local.

  SECTION B -- real BYOK preference, with get_openai_client_for_tenant_sync
  itself UNMOCKED. A tenant with a real (fake, never sent anywhere) BYOK
  key configured must get a client whose .api_key is that tenant's key;
  a tenant with no BYOK key configured must fall back to the platform
  key. This is byok.py's own logic under real DB-backed BYOK storage, not
  a mock.

Runs against an isolated temp copy of backend/ (never the real
eivanta.duckdb) and cleans up after itself, exactly like verify_mcp_server.py.
"""
import os
import sys
import json
import shutil
import asyncio
import tempfile
import traceback
import duckdb

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/


def _copy_isolated_backend(tmp_root: str) -> str:
    dest = os.path.join(tmp_root, "backend")
    shutil.copytree(
        PROJECT_ROOT,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.duckdb", "*.db", "venv", "_to_delete", "*.pyc"),
    )
    return dest


class _StubResponse:
    def __init__(self):
        raise RuntimeError("verify_byok_rollout: stub-raise-to-confirm-reached")


class _StubChatCompletions:
    def create(self, *args, **kwargs):
        raise RuntimeError("verify_byok_rollout: stub-raise-to-confirm-reached")


class _StubChat:
    def __init__(self):
        self.completions = _StubChatCompletions()


class _StubClient:
    def __init__(self):
        self.chat = _StubChat()


def main() -> int:
    tmp_root = tempfile.mkdtemp(prefix="eivanta_byok_verify_")
    ok = True
    try:
        backend_dir = _copy_isolated_backend(tmp_root)
        sys.path.insert(0, tmp_root)

        # A fresh Fernet key + fake platform key -- BYOK_ENCRYPTION_KEY must
        # be set before backend.byok is ever imported (it refuses to start
        # without one, by design -- see byok.py's own module docstring).
        from cryptography.fernet import Fernet
        os.environ["BYOK_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        os.environ["OPENAI_API_KEY"] = "sk-platform-fake-key-never-sent-anywhere"

        from backend import db_manager
        from backend import byok
        from backend.agents import (
            virtual_cfo,
            bi_engineer,
            predictive_forecaster,
            report_generator,
            saas_strategist,
            data_engineer,
            bi_visualization_architect,
            external_telemetry_scout,
        )

        async def _seed():
            await db_manager.init_db()
            tenant = "verify_byok_tenant"
            csv_path = os.path.join(backend_dir, "verify_byok_seed.csv")
            with open(csv_path, "w") as f:
                f.write("date,category,amount,description\n")
                # 5 distinct months, revenue + expense -- enough for
                # predictive_forecaster's MIN_PERIODS_FOR_FORECAST (4) and
                # for every other agent's "do we have any real data" gate.
                rows = [
                    ("2026-04-05", "Revenue", 4000.0, "seed"),
                    ("2026-04-20", "Software", -300.0, "seed"),
                    ("2026-05-05", "Revenue", 4200.0, "seed"),
                    ("2026-05-20", "Software", -310.0, "seed"),
                    ("2026-06-05", "Revenue", 4500.0, "seed"),
                    ("2026-06-20", "Software", -290.0, "seed"),
                    ("2026-07-05", "Revenue", 4700.0, "seed"),
                    ("2026-07-20", "Software", -320.0, "seed"),
                    ("2026-08-05", "Revenue", 5000.0, "seed"),
                    ("2026-08-20", "Software", -305.0, "seed"),
                ]
                for d, cat, amt, desc in rows:
                    f.write(f"{d},{cat},{amt},{desc}\n")
            await db_manager.ingest_csv_to_db(csv_path, tenant, "verify_byok_seed.csv")
            return tenant

        tenant_id = asyncio.run(_seed())

        # ---------------------------------------------------------------
        # SECTION A -- call-site wiring, get_openai_client_for_tenant_sync
        # monkeypatched per-module.
        # ---------------------------------------------------------------
        calls = []

        def _spy(client_id, platform_api_key, timeout, max_retries):
            calls.append({"client_id": client_id, "platform_api_key": platform_api_key})
            return _StubClient()

        modules = [
            virtual_cfo, bi_engineer, predictive_forecaster, report_generator,
            saas_strategist, data_engineer, bi_visualization_architect, external_telemetry_scout,
        ]
        for m in modules:
            m.get_openai_client_for_tenant_sync = _spy

        checks = []

        def _run(label, fn, *args, **kwargs):
            before = len(calls)
            try:
                fn(*args, **kwargs)
            except Exception as e:
                # Some call sites (the two _summarize_with_llm helpers)
                # return a plain list rather than raising -- either way,
                # only the spy call matters here.
                pass  # nosec B110
            after_calls = calls[before:]
            passed = len(after_calls) >= 1 and all(c["client_id"] == tenant_id for c in after_calls)
            checks.append((label, passed, after_calls))

        _run("virtual_cfo.generate_cfo_briefing", virtual_cfo.generate_cfo_briefing, tenant_id)
        _run("bi_engineer._ask_llm_for_query_intent", bi_engineer._ask_llm_for_query_intent, tenant_id, "how much did I spend on software")
        _run("bi_engineer.generate_bi_summary", bi_engineer.generate_bi_summary, tenant_id)
        _run("predictive_forecaster.generate_forecast", predictive_forecaster.generate_forecast, tenant_id)
        _run("report_generator.generate_stakeholder_report", report_generator.generate_stakeholder_report, tenant_id)
        _run("saas_strategist.generate_strategy", saas_strategist.generate_strategy, tenant_id)
        _run("data_engineer.analyze_schema_quality", data_engineer.analyze_schema_quality, tenant_id)
        _run(
            "bi_visualization_architect._summarize_with_llm",
            bi_visualization_architect._summarize_with_llm,
            tenant_id, "show revenue trend", "line", {}, {},
        )
        _run(
            "external_telemetry_scout._summarize_with_llm",
            external_telemetry_scout._summarize_with_llm,
            tenant_id, "flatten this payload", {"amount": "DOUBLE"}, {"amount": 10.0},
        )

        print(f"\n=== SECTION A: call-site wiring (tenant={tenant_id!r}) ===")
        for label, passed, after_calls in checks:
            status = "ok" if passed else "FAILED"
            print(f"  [{status}] {label}  (spy calls: {after_calls})")
            if not passed:
                ok = False

        # ---------------------------------------------------------------
        # SECTION B -- real BYOK preference, unmocked.
        # ---------------------------------------------------------------
        for m in modules:
            del m.get_openai_client_for_tenant_sync  # drop the spy override, restore real import binding
        import importlib
        importlib.reload(byok)

        real_platform_key = "sk-platform-fake-key-never-sent-anywhere"
        fake_byok_key = "sk-tenant-byok-fake-key-never-sent-anywhere"

        # Tenant WITH a configured BYOK key -> must get a client scoped to it.
        encrypted = byok.encrypt_secret(fake_byok_key)

        async def _store_byok(cid, enc):
            # ingest_csv_to_db (used in _seed above) only ever touches the
            # ledgers table -- it never creates a `tenants` row. Insert one
            # here (this script's own setup responsibility, not something
            # byok.py should do) before the key can be attached to it.
            with db_manager.get_db_lock():
                conn = duckdb.connect(db_manager.DB_PATH)
                try:
                    conn.execute("INSERT INTO tenants (client_id, company_name) VALUES (?, ?)", [cid, "Verify BYOK Co"])
                    conn.execute(
                        "UPDATE tenants SET byok_openai_key_encrypted = ? WHERE client_id = ?",
                        [enc, cid],
                    )
                finally:
                    conn.close()

        asyncio.run(_store_byok(tenant_id, encrypted))

        client_with_byok = byok.get_openai_client_for_tenant_sync(
            tenant_id, real_platform_key, 30.0, 2
        )
        byok_ok = client_with_byok is not None and client_with_byok.api_key == fake_byok_key
        print(f"\n=== SECTION B: real BYOK preference ===")
        print(f"  [{'ok' if byok_ok else 'FAILED'}] tenant WITH a BYOK key gets that key's client (got api_key={getattr(client_with_byok, 'api_key', None)!r})")
        if not byok_ok:
            ok = False

        # A tenant with no BYOK key configured at all -> must fall back to
        # the platform key.
        no_byok_tenant = "verify_byok_tenant_no_key"

        async def _create_bare_tenant(cid):
            with db_manager.get_db_lock():
                conn = duckdb.connect(db_manager.DB_PATH)
                try:
                    conn.execute("INSERT INTO tenants (client_id, company_name) VALUES (?, ?)", [cid, "No BYOK Co"])
                finally:
                    conn.close()

        asyncio.run(_create_bare_tenant(no_byok_tenant))
        client_without_byok = byok.get_openai_client_for_tenant_sync(
            no_byok_tenant, real_platform_key, 30.0, 2
        )
        fallback_ok = client_without_byok is not None and client_without_byok.api_key == real_platform_key
        print(f"  [{'ok' if fallback_ok else 'FAILED'}] tenant with NO BYOK key falls back to the platform key (got api_key={getattr(client_without_byok, 'api_key', None)!r})")
        if not fallback_ok:
            ok = False

    except Exception:
        print("\nverify_byok_rollout.py crashed:")
        traceback.print_exc()
        ok = False
    finally:
        sys.path = [p for p in sys.path if p != tmp_root]
        shutil.rmtree(tmp_root, ignore_errors=True)

    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
