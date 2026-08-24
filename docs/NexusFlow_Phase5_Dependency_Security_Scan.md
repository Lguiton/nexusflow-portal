# Phase 5 -- Dependency / Security Scanning

Part of the SaaS Lifecycle Executive Manual's Phase 5 (Testing & QA) gap:
"add dependency/security scanning (npm audit/Snyk/SAST)."

## Frontend -- npm audit (done, real result on record)

Ran as part of installing the Jest/Playwright dev dependencies:

```
added 306 packages, and audited 717 packages in 1m
found 0 vulnerabilities
```

`npm audit` walks the full resolved dependency tree from
`package-lock.json`, not just newly-added packages, so this is a real,
whole-project result: **0 known vulnerabilities across all 717 resolved
frontend packages** as of 2026-08-23.

To re-run later (worth doing periodically, and again before any real
production deploy, since new CVEs get disclosed against existing pinned
versions over time -- a clean audit today doesn't stay clean forever):

```bash
cd frontend
npm audit
```

## Backend -- pip-audit (not yet run -- needs to happen on your side)

I could not run this myself. Both of my execution paths are network-
isolated from the outside world -- my own cloud sandbox and the separate
VM behind the device bridge into your project both sit behind an egress
allowlist that blocks PyPI, so `pip install pip-audit` 403s from either
side. Your own WSL venv (where `run-backend` and the jest/playwright
installs already worked) has real internet access, so this needs to run
there:

```bash
# from your WSL venv, already active in your terminal
pip install pip-audit
pip-audit -r backend/requirements.txt
```

`backend/requirements.txt` as of this scan:

```
fastapi
uvicorn[standard]
langgraph
duckdb
pandas
numpy
scipy
openai
PyJWT
python-dotenv
pydantic
httpx
python-multipart
```

None of these are pinned to exact versions, so `pip-audit` will check
whatever your venv actually has installed -- if it flags something, the
fix is almost always bumping that one package, not a code change. Paste
me the output and I'll help work through anything it finds.

## SAST (static analysis) -- not started, worth flagging rather than
## silently deciding

The Phase 5 gap mentions SAST alongside dependency scanning. I haven't
run or set one up, because "which SAST tool, run how, gating what" is a
real process decision (a one-off local run vs. wiring into CI, `bandit`
for the Python side vs. something heavier, whether findings should block
a deploy) rather than something with one obviously-correct default the
way `npm audit`/`pip-audit` are. A reasonable, low-effort starting point
if you want one now:

```bash
# backend -- flags things like eval/exec use, hardcoded secrets, sql
# string-building, etc.
pip install bandit
bandit -r backend -x backend/tests

# frontend -- ESLint is already configured (`npm run lint`); the
# `eslint-plugin-security` rules aren't enabled by default and would need
# to be added deliberately if you want that coverage too.
cd frontend && npm run lint
```

I haven't run either of these -- flagging them here rather than running
tools against your codebase and deciding on your behalf which one
"counts" as done.

## Status

- Frontend dependency scan: **done**, clean (0/717).
- Backend dependency scan: **handed off** -- commands above, needs your
  venv's real internet access.
- SAST: **not started**, flagged above as an open decision rather than
  silently picked for you.
