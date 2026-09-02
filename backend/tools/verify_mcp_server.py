"""
INT-01: real, end-to-end verification of the MCP tool server (backend/
mcp_server.py) and its API-key auth (backend/api_keys.py) -- against the
REAL backend.main:app, a REAL uvicorn process, and the REAL mcp client
SDK speaking real Streamable HTTP. Not a stub, not a mock.

Why this is a standalone script and not a pytest file (see backend/tests/
test_api_keys.py's own docstring for the REST-layer pytest coverage that
DOES exist): the MCP SDK's Streamable HTTP transport includes a real
DNS-rebinding Host-header check, which rejects FastAPI TestClient's fake
"testserver" host outright. A real bound host:port is the only way to
exercise the actual protocol handshake, so this script launches a REAL
uvicorn subprocess -- same pattern as tools/model_regression_check.py's
own "needs a real environment, disclose the limit rather than fake it"
posture.

Safety: runs against an ISOLATED TEMP COPY of the backend/ directory, not
the real one -- so db_manager.DB_PATH (computed from wherever
db_manager.py physically lives) resolves inside that temp copy's own
throwaway eivanta.duckdb, and this script can never read, write, or
touch a real tenant's data. The temp copy is deleted on exit.

Usage:
    python backend/tools/verify_mcp_server.py

Exit code 0 and "ALL CHECKS PASSED" on success; non-zero and a real
traceback/assertion message on any failure -- never a silent skip.
"""
import asyncio
import json
import os
import shutil
import socket
import subprocess  # nosec B404 -- both call sites below use a fixed argv list, no shell=True, no external/untrusted input
import sys
import tempfile
import time

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_THIS_DIR)  # backend/


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError(f"Server never came up on port {port} within {timeout}s.")


async def _seed_and_get_key(project_root: str, tenant_id: str, label: str) -> dict:
    """
    Runs IN a short-lived subprocess (not this script's own process) so
    its db_manager import resolves DB_PATH against the temp copy, exactly
    like the real server subprocess does -- never against whatever
    db_manager happens to already be imported as in this script's process.
    """
    seed_code = f"""
import asyncio, json, sys, os
sys.path.insert(0, {project_root!r})
from backend import db_manager as dm

async def main():
    await dm.init_db()
    key = await dm.generate_api_key({tenant_id!r}, {label!r}, created_by_user_id=1)
    csv_path = os.path.join({project_root!r}, "verify_mcp_seed.csv")
    with open(csv_path, "w") as f:
        f.write("date,category,amount,description\\n2026-08-01,Revenue,750.0,verify_mcp_server seed row\\n")
    await dm.ingest_csv_to_db(csv_path, {tenant_id!r}, "verify_mcp_seed.csv")
    print(json.dumps(key, default=str))

asyncio.run(main())
"""
    proc = subprocess.run(  # nosec B603 -- fixed argv (sys.executable + this script's own literal seed_code), no shell, no external input
        [sys.executable, "-c", seed_code],
        cwd=project_root, capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Seeding failed:\n{proc.stdout}\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


async def _run_mcp_checks(base_url: str, api_key: str) -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": f"Bearer {api_key}"}
    bad_headers = {"Authorization": "Bearer evta_live_totallyfake"}
    url = f"{base_url}/mcp/"

    async def call(hdrs, name, args=None):
        async with streamablehttp_client(url, headers=hdrs) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(name, args or {})

    async def list_tools(hdrs):
        async with streamablehttp_client(url, headers=hdrs) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.list_tools()

    tools = await list_tools(headers)
    names = sorted(t.name for t in tools.tools)
    expected = {
        "get_bi_summary", "get_forecast", "get_ledger_rows",
        "get_kpi_summary", "get_mrr_summary", "get_assumptions", "get_known_gaps",
    }
    assert expected.issubset(set(names)), f"Missing tools: {expected - set(names)}"
    print(f"  [ok] all 7 read-only tools registered: {names}")

    result = await call(headers, "get_kpi_summary")
    assert result.isError is not True, result.content[0].text
    data = json.loads(result.content[0].text)
    assert data["ledger_row_count"] == 1, data
    assert data["ledger_total_amount"] == 750.0, data
    print("  [ok] get_kpi_summary returns real seeded ledger data")

    try:
        await call(bad_headers, "get_known_gaps")
        raise AssertionError("an invalid API key must be rejected")
    except AssertionError:
        raise
    except Exception:
        print("  [ok] invalid API key rejected before reaching a tool")

    try:
        await call({}, "get_known_gaps")
        raise AssertionError("a missing Authorization header must be rejected")
    except AssertionError:
        raise
    except Exception:
        print("  [ok] missing Authorization header rejected")


def main() -> int:
    tmp_root = tempfile.mkdtemp(prefix="eivanta_mcp_verify_")
    server_proc = None
    try:
        tmp_backend = os.path.join(tmp_root, "backend")
        shutil.copytree(_BACKEND_DIR, tmp_backend, ignore=shutil.ignore_patterns(
            "__pycache__", "*.duckdb", "*.db", ".venv", "venv", "_to_delete",
        ))
        open(os.path.join(tmp_backend, "__init__.py"), "a").close()
        open(os.path.join(tmp_backend, "agents", "__init__.py"), "a").close()

        port = _free_port()
        env = dict(os.environ)
        env["JWT_SECRET"] = "verify-script-secret-not-for-production"  # nosec B105 -- throwaway env for this script's own isolated temp subprocess only
        env.setdefault("OPENAI_API_KEY", "sk-verify-placeholder-not-a-real-key")

        print(f"Starting real backend.main:app on 127.0.0.1:{port} (isolated temp copy at {tmp_root}) ...")
        server_proc = subprocess.Popen(  # nosec B603 -- fixed argv, port is OS-assigned via _free_port(), no shell, no external input
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=tmp_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        _wait_for_port(port)

        tenant_id = "verify_mcp_server_tenant"
        key = asyncio.run(_seed_and_get_key(tmp_root, tenant_id, "verify_mcp_server.py"))
        print(f"  [ok] seeded isolated tenant '{tenant_id}' with a real API key")

        asyncio.run(_run_mcp_checks(f"http://127.0.0.1:{port}", key["api_key"]))

        print("\nALL CHECKS PASSED")
        return 0
    except Exception:
        import traceback
        traceback.print_exc()
        if server_proc is not None:
            server_proc.poll()
            if server_proc.stdout is not None:
                print("\n--- server output ---")
                try:
                    print(server_proc.stdout.read())
                except Exception:
                    pass  # nosec B110 -- best-effort extra debug output on an already-failing path; nothing more to do if this also fails
        return 1
    finally:
        if server_proc is not None and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_proc.kill()
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
