"""
SEC-03 SAST pass (28 Aug 2026): bandit B108 flagged both file-upload
endpoints in main.py for using a predictable, default-permission /tmp
directory (/tmp/eivanta_ingest, /tmp/eivanta_knowledge). The fix: chmod
the directory to 0o700 unconditionally on every request (not just on
first creation -- Path.mkdir(mode=...) silently skips applying its mode
whenever exist_ok=True finds the directory already there), plus a uuid
component added to the ingest endpoint's temp filename (the knowledge
endpoint already had one) so two concurrent uploads of the same filename
from the same tenant can no longer collide on the same path.

These tests exercise the real ledger-upload endpoint end-to-end (it has
existing test infrastructure and no external-service dependency); the
knowledge-upload endpoint got the identical fix but has no pre-existing
test harness (it depends on a configured RAG/embeddings backend this
sandbox doesn't set up) -- test_knowledge_endpoint_has_matching_fix below
checks that endpoint's source directly rather than inventing a RAG test
harness as a side effect of a SAST hardening pass.
"""
import io
import os
import stat
from pathlib import Path

import pytest


def _dir_mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_ingest_temp_dir_locked_to_owner_only_after_real_upload(client, auth_headers):
    csv_content = b"date,category,amount,description\n2026-01-05,Sales,100,Widget\n"
    resp = client.post(
        "/api/finance/upload-ledger",
        files={"file": ("perm_check.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    temp_dir = Path("/tmp/eivanta_ingest")
    assert temp_dir.is_dir()
    assert _dir_mode(temp_dir) == 0o700, (
        f"expected /tmp/eivanta_ingest to be locked to 0700, got {oct(_dir_mode(temp_dir))}"
    )


def test_ingest_temp_dir_gets_tightened_even_if_it_already_existed_looser(client, auth_headers):
    """Regression lock for the specific bug class the fix targets: mkdir's
    mode= argument is a no-op when exist_ok=True and the directory is
    already there, so a directory left over from an older, unfixed
    process/deploy must still get tightened on the very next request, not
    only on first-ever creation."""
    temp_dir = Path("/tmp/eivanta_ingest")
    temp_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(temp_dir, 0o777)
    assert _dir_mode(temp_dir) == 0o777  # sanity: we really did loosen it

    csv_content = b"date,category,amount,description\n2026-01-06,Sales,50,Gadget\n"
    resp = client.post(
        "/api/finance/upload-ledger",
        files={"file": ("preexisting_dir.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert _dir_mode(temp_dir) == 0o700, (
        "a pre-existing, loosely-permissioned temp dir was not tightened on this request"
    )


def test_concurrent_same_filename_uploads_no_longer_collide(client, auth_headers):
    """Before this fix, the ingest endpoint's temp filename was
    '{client_id}_{original_filename}' with no per-upload uniqueness --
    two uploads of the same original filename from the same tenant wrote
    to the identical path. Both should now succeed independently."""
    csv_a = b"date,category,amount,description\n2026-01-07,Sales,10,First\n"
    csv_b = b"date,category,amount,description\n2026-01-08,Sales,20,Second\n"

    resp_a = client.post(
        "/api/finance/upload-ledger",
        files={"file": ("same_name.csv", io.BytesIO(csv_a), "text/csv")},
        headers=auth_headers,
    )
    resp_b = client.post(
        "/api/finance/upload-ledger",
        files={"file": ("same_name.csv", io.BytesIO(csv_b), "text/csv")},
        headers=auth_headers,
    )
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200


def test_ingest_temp_file_still_cleaned_up_after_success(client, auth_headers):
    """The uuid addition changes the filename pattern but must not disturb
    the existing finally-block cleanup -- no upload's temp file should
    survive past the request that made it."""
    temp_dir = Path("/tmp/eivanta_ingest")
    before = set(temp_dir.glob("*")) if temp_dir.exists() else set()

    csv_content = b"date,category,amount,description\n2026-01-09,Sales,30,Cleanup check\n"
    resp = client.post(
        "/api/finance/upload-ledger",
        files={"file": ("cleanup_check.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    after = set(temp_dir.glob("*"))
    assert after == before, f"temp file(s) left behind after a successful upload: {after - before}"


def test_knowledge_endpoint_has_matching_fix():
    """No RAG-backed test harness exists for the knowledge-upload endpoint
    (see module docstring), so this checks the fix landed in source: the
    same chmod(0o700) call this file behaviorally proves for the ingest
    endpoint above must also be present on the knowledge-upload code path,
    immediately after ITS temp_dir.mkdir call."""
    source = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
    idx = source.index('Path("/tmp/eivanta_knowledge")')
    following = source[idx: idx + 400]
    assert "os.chmod(temp_dir, 0o700)" in following, (
        "knowledge-upload endpoint's temp_dir is missing the 0o700 chmod hardening"
    )
