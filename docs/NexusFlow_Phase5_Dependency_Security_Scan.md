# Phase 5 -- Dependency / Security Scanning

Part of the SaaS Lifecycle Executive Manual's Phase 5 (Testing & QA) gap:
"add dependency/security scanning (npm audit/Snyk/SAST)." Also closes the
dependency-scanning half of Master Build List item SEC-03.

## UPDATE 28 Aug 2026 -- first real backend SAST pass (bandit), by hand

The SAST section below (23/27 Aug) explicitly left the tool-choice
decision open rather than silently picking one -- `bandit` was named as
"a reasonable, low-effort starting point if you want one." You didn't
have to ask: this is exactly the kind of mechanical, non-founder-gated
work this pass has been running on autopilot for, so I ran it.

```bash
bandit -r backend -x backend/tests
```

**45 findings on the first run.** Rather than report "45 issues found" and
stop -- which would be closer to noise than a real audit -- every finding
of MEDIUM severity or above (9 of the 45; the other 36 were LOW) got
read, traced to its actual call sites, and judged on real evidence, not
bandit's pattern-matching alone:

- **6 were confirmed false positives** -- bandit flags any f-string near
  SQL keywords, with no idea that this codebase already has a real
  whitelist design (SQL-01) behind every one of them. Two in
  `agents/bi_engineer.py` (one isn't even SQL -- it's an LLM prompt
  string bandit mistook for one; the other builds SQL exclusively from
  fixed vocabulary dicts, real values always parameter-bound) and four in
  `db_manager.py` (table/column names always drawn from a fixed source
  constant or a real schema introspection, never user input). 5 of the 6
  got a `# nosec B608` annotation with a one-line justification right at
  the call site, so a future bandit run reports these as closed instead
  of re-flagging them for re-review every time; the 6th (a multi-line
  f-string) couldn't take an inline annotation without corrupting the
  string it opens -- caught that exact mistake mid-edit and reverted it
  before it shipped -- so it's documented in a comment above instead of
  machine-suppressed.
- **2 were real and got actually fixed**: both file-upload endpoints
  (`/api/finance/upload-ledger` and the knowledge-base uploader) wrote
  into a predictable `/tmp/...` directory with default, umask-derived
  permissions -- typically world-readable. Now `os.chmod`'d to `0700`
  unconditionally on every request (not just on first creation --
  `Path.mkdir(mode=...)` silently skips applying its mode whenever the
  directory already exists, which would have left an already-deployed,
  looser-permissioned directory unfixed by this patch). Caught a second,
  related bug for free while in that code: the ledger-upload endpoint's
  temp filename had no per-upload uniqueness, so two concurrent uploads
  of the same filename from the same tenant could collide on the same
  path -- fixed the same way the knowledge endpoint already handled it
  (a uuid component). 5 new tests lock both fixes in, including one that
  deliberately pre-loosens the directory to 0777 before a request to
  prove the chmod isn't skipped on a pre-existing directory. Full backend
  suite: 353 passed (348 + 5 new), 6 skipped, zero regressions.
- **1 is real and deliberately NOT fixed**: `backend/app/etl/pipeline.py`
  builds a SQL statement from an unvalidated `table_name` parameter with
  no whitelist -- a genuine injection-shaped pattern. But this class
  (`OpsDataPipeline.load_to_postgres`) has zero callers anywhere in the
  codebase -- confirmed by grep, not assumption. It looks like leftover
  scaffolding from an earlier Postgres-based architecture the DuckDB
  migration superseded. Patching dead code and calling it "fixed" would
  be theater (nothing executes it, so nothing is actually safer), and
  deleting it is a real scope call I'm not making unilaterally -- you may
  still want this file for a future integration. Flagging it here as a
  genuine open item: either delete `backend/app/etl/pipeline.py` (and
  confirm nothing external references it) or, if it's ever wired up
  in, fix `table_name` to go through the same kind of whitelist SQL-01
  already uses everywhere else.
- **The other 36 LOW-severity findings were not individually reviewed**
  this pass -- mostly `assert` usage inside test files (not a real
  vulnerability class; bandit flags it because `-O` strips asserts in
  production, irrelevant to a test file) and `except: pass` patterns
  already consistent with this codebase's established "fail open on a
  non-critical path, log elsewhere" philosophy. Worth a deliberate look
  eventually, not urgent.

Frontend SAST (`eslint-plugin-security`) is still genuinely not run --
see the unchanged section below.

## UPDATE 27 Aug 2026 -- backend gap closed, both scans re-run for real

The original scan below (23 Aug 2026) could only complete the frontend
half -- at that time, neither of Claude's own execution environments had
outbound network access to PyPI, so `pip-audit` 403'd from both and had
to be handed off to run on your own machine.

That's no longer true of the current cloud sandbox (confirmed by
successfully installing `pytest`, `pip-audit`, and `npm` packages from
their real registries this session) -- so both scans below were run for
real, today, by Claude, not handed off:

```
--- Backend (pip-audit 2.10.1) ---
No known vulnerabilities found
88 resolved packages scanned, 0 with known vulnerabilities.

--- Frontend (npm audit) ---
found 0 vulnerabilities
785 resolved packages scanned (up from 717 on 23 Aug -- Jest/Playwright/
testing-library additions since then), 0 known vulnerabilities.
```

Both trees are clean as of this run. A clean result today doesn't stay
clean forever (new CVEs get disclosed against already-pinned versions
over time), so this is now a real, standing script rather than a
one-off:

```bash
./scripts/security_scan.sh
```

Runs both scans, prints a clear summary, and exits non-zero if either
finds a real issue -- worth re-running periodically, and again before
any real production deploy. It self-installs `pip-audit` from
`backend/requirements-dev.txt` (a new file -- dev/CI tooling only, never
part of the production image) if it isn't already on your PATH.
`backend/requirements.txt` itself is unchanged by this update.

Scope, stated plainly: this is DEPENDENCY scanning only. SEC-03's title
also names container-image scanning and penetration testing, and neither
is covered here -- container scanning needs a built image to scan
against (see `docker/`, and CICD-01 which isn't built yet), and pentest
tooling has no obviously-correct default the way `pip-audit`/`npm audit`
do. Both remain genuinely open.

## Frontend -- npm audit (original result, 23 Aug 2026 -- superseded by the re-run above)

Ran as part of installing the Jest/Playwright dev dependencies:

```
added 306 packages, and audited 717 packages in 1m
found 0 vulnerabilities
```

## Backend -- pip-audit (original status, 23 Aug 2026 -- CLOSED by the re-run above)

I could not run this myself at the time. Both of my execution paths were
network-isolated from the outside world -- my own cloud sandbox and the
separate VM behind the device bridge into your project both sat behind
an egress allowlist that blocked PyPI, so `pip install pip-audit` 403'd
from either side. See the 27 Aug update above for why that's no longer
the blocker it was.

## SAST (static analysis) -- backend now real (28 Aug), frontend still open

Backend: see the 28 Aug update above -- `bandit` has now actually run
against `backend/`, every MEDIUM+ finding was investigated by hand, 2
real gaps got fixed with tests, 5 false positives are now suppressed
with a documented reason, and 1 real-but-dead-code finding is flagged
for your decision rather than silently patched or deleted. Not wired
into `scripts/security_scan.sh` yet -- that script stays dependency-only
by design (see its own header comment); whether SAST should gate a
deploy the way dependency scanning does is a real process decision
still worth making deliberately, not bundling in by default.

Frontend: still genuinely not run. ESLint is already configured (`npm
run lint`), but the `eslint-plugin-security` rules aren't enabled by
default and would need to be added deliberately:

```bash
cd frontend && npm install --save-dev eslint-plugin-security
# then add it to the ESLint config and: npm run lint
```

I still haven't done this -- flagging it here rather than running a tool
against your codebase and deciding on your behalf that it "counts" as
done.

## Status

- Frontend dependency scan: **done**, clean (0/785, re-run 27 Aug 2026).
- Backend dependency scan: **done**, clean (0/88, run 27 Aug 2026 -- no
  longer handed off).
- Combined, repeatable script: **done** -- `scripts/security_scan.sh`
  (dependency scanning only, by design).
- Backend SAST: **first real pass done** (28 Aug 2026, bandit) -- 2 real
  findings fixed and tested, 5 false positives documented/suppressed, 1
  real-but-dead-code finding flagged as an open decision, 36 low-severity
  findings not yet individually reviewed. Not wired into the standing
  script.
- Frontend SAST: **not started** -- `eslint-plugin-security` isn't
  installed; flagged above rather than silently added for you.
- Container image scanning and penetration testing: **not addressed**,
  same as always -- see the 27 Aug update's scope note above.
