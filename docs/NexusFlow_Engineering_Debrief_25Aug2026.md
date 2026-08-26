# NexusFlow Analytics — Engineering Debrief

**25 August 2026 | RBAC-01 (real authentication, roles, team management) + Phase 6 DevOps/CI-CD scaffolding + self-review pass**

This debrief covers everything delivered to the live codebase this engagement, what changed and why, the bugs a self-review pass caught before you saw them, and the honest limits of what could and couldn't be verified in this environment. It follows the same narrative format as `NexusFlow_Engineering_Debrief_23Aug2026.md`, but does not re-dump full file contents inline — every changed file was already delivered to you individually as a download during the session, and the current, real content is what's committed in your repo now.

---

## Part 1 — What Changed, and Why

**RBAC-01 (real authentication):** The platform's auth was, until this engagement, a `dev-login` endpoint that accepted any `client_id` string, no password, and handed back a real signed JWT — fine for early prototyping, not a real login system. `backend/db_manager.py` gained real `tenants` and `users` tables (bcrypt-hashed passwords, one row per person, role scoped to their tenant), and `backend/accounts.py` gained real `POST /api/v1/auth/signup` and `POST /api/v1/auth/login` endpoints. Signup creates a tenant and its first user — always role `owner` — atomically in one transaction, and logs you straight in (it returns an access token immediately, no separate login step needed). Login verifies a bcrypt hash, with a constant-shape dummy-hash fallback for unknown emails so a login attempt can't be used to enumerate real accounts by response timing. The old `/api/v1/auth/dev-login` endpoint is retired outright, not just deprecated — it now 404s.

**RBAC-01 (role gating + team management):** A four-role model — Owner / Admin / Member / Viewer, per your direction — is enforced via a `require_role()` FastAPI dependency factory across every mutating or destructive endpoint: ledger upload and delete (`main.py`), category-suggestion apply (`categorization.py`), and the three platform metrics endpoints (`metrics.py`, restricted to owner/admin). That metrics restriction is a partial mitigation only — the underlying data those endpoints serve is still platform-wide, not filtered per tenant, which is a separate data-layer gap tracked as OPS-07 in the Master Build List, not fixed by this pass. Full team management shipped in `backend/accounts.py`: invite (owner/admin only), list (any role can see the roster), role change and removal (owner only), with self-demote and self-remove both explicitly blocked so a tenant can never end up ownerless by accident.

**Frontend auth flow:** `frontend/components/ClientContext.tsx` was rewritten around the real login/signup endpoints instead of the old always-auto-authenticate dev-login call — it now only restores a session from an already-stored token (validated against `/api/v1/auth/me`), otherwise it settles to signed-out with zero network calls. A new `AuthGate.tsx` component gates the whole app behind a real sign-in/sign-up form. `AppShell.tsx` now shows the signed-in user's real email and role in the sidebar with a working sign-out control, and hides the topbar "Upload Ledger" shortcut for viewers, matching the backend's new upload restriction.

**Test-fixture migration:** `backend/tests/conftest.py`'s auth fixtures were rebuilt on the real account-creation functions instead of the retired dev-login endpoint. A new RBAC test section covers role-gating on every touched endpoint, and a new `test_accounts.py` covers the full team-management surface — roughly 25 new checks in total. On the frontend, five existing Jest test files had quietly stopped testing anything real once `ClientContext.tsx` changed (see the self-review entry below) and were rewritten against the real session-restore flow.

**Phase 6 (DevOps / CI-CD scaffolding):** Local Docker/CI scaffolding was written — `docker-compose.yml` and Dockerfiles for both backend and frontend — plus a GitHub Actions CI workflow (lint / test / build) on merge. `.github/workflows/` is a protected path in this environment and couldn't be committed automatically, so that one file was delivered to you as a download for you to place by hand. A Terraform skeleton was also written, using the real `vercel/vercel` and `render-oss/render` Terraform provider resource schemas (checked against their actual documentation, not guessed) to cover a future Vercel + Render deployment. None of this was executed — `terraform validate`/`plan`/`apply` all require network access this environment doesn't have — so it's explicitly scaffolding, reviewed but unrun, not a live deployment.

**Founder decisions locked in this engagement:** RBAC role model = Owner / Admin / Member / Viewer. Billing = a single flat paid tier (not the three-tier plan the original build list assumed) — Stripe integration itself is deferred pending your own Stripe credentials. Transactional email = Resend, deferred pending your own Resend credentials. Real deployment (Vercel/Render) remains deferred pending your own hosting accounts. None of these three is technically blocked on anything but credentials only you can provide.

---

## Part 2 — Self-Review: Two Real Bugs Found and Fixed

Before writing this debrief, I went back and re-read every changed file against the real code actually committed to your repo — not my working draft — specifically to check my own prior "done" report rather than just trust it. That pass caught two real defects, both fixed and redelivered before you saw this document:

**1. `db_manager.py` — a DuckDB-incompatible function call that would have 500'd two live endpoints.** `update_user_role()` and `remove_user()` both called `SELECT changes()` after their UPDATE/DELETE statement to check whether a row was actually affected. `SELECT changes()` is a SQLite-only function — DuckDB, which this project actually uses, has no such function. Every real call to the role-change or remove-teammate endpoints would have thrown a Catalog/Binder error instead of ever returning a clean true/false. I confirmed this against DuckDB's own documentation and a GitHub discussion on the topic, then fixed both functions to use an explicit existence-check (`SELECT 1 FROM users WHERE ...`) before the write — the same pattern this file already uses elsewhere (`delete_tenant_ledger`), so the fix is also stylistically consistent with the rest of the file.

**2. Five frontend Jest test files silently broken by the `ClientContext.tsx` rewrite.** `ClientContext.test.tsx`, `AssumptionLedger.test.tsx`, `SubAgentWidget.test.tsx`, `SwarmLogStreamer.test.tsx`, and `KnownGapsPanel.test.tsx` all mocked the retired `/api/v1/auth/dev-login` endpoint as their setup mechanism. Once `ClientContext.tsx` stopped auto-authenticating on every mount, those mocks became dead code that would never fire. I traced each widget's real source to gauge exact severity before touching anything: `SwarmLogStreamer.tsx` treats a null auth token as a hard "Authentication Failed" state, so all four of its tests would have failed outright; `SubAgentWidget.test.tsx`'s Authorization-header assertion would fail since no real token would ever populate; `AssumptionLedger.test.tsx` and `KnownGapsPanel.test.tsx` were less severely broken but still testing a dead path. All five were rewritten to seed a real session token and mock `/api/v1/auth/me` instead — the genuine equivalent of what dev-login mocking used to simulate.

**A mistake in my own process, worth disclosing:** while redelivering those six fixed files, I re-staged the same six paths from your machine a second time as an intended "drift check" before commit — that staging call unconditionally overwrote my already-fixed local copies with the stale, still-buggy content still on your disk (since nothing had been committed to your machine yet). I caught this immediately from the tool's own change notifications, confirmed the damage, and redid all six edits from scratch, this time delivering and committing without any further re-staging in between. Net effect on you: zero — nothing was ever pushed to your repo in the broken state — but it cost a round of rework and is worth naming so you know it happened.

---

## Part 3 — Verification Methodology (and Its Real Limits)

Backend changes were syntax-checked with `py_compile` against every touched file, including a full combined pass immediately before delivery. Frontend changes were type-checked with a real `tsc --noEmit` run against your actual project's `node_modules` and `tsconfig.json` — scoped to the changed files and their real transitive imports rather than the whole project, because a whole-project run exceeded this environment's execution time limit against the file-bridge's real I/O speed. Every scoped run came back clean. bcrypt's hash/verify logic was execution-verified, not just reviewed, by cross-linking a Python interpreter in this environment to your project's real virtual environment's installed bcrypt package.

Two things could **not** be execution-verified, and I want to be direct about that rather than let it slide: a live `jest` run and a live `pytest` run were both attempted (multiple times, in different forms) and both blocked by the same file-bridge speed limit that affected `tsc`. The five rewritten Jest test files were instead verified by carefully tracing each widget's real component source code against the test's expectations — a real check, but not the same thing as watching the suite actually pass. **I'd recommend you run `npm test` and your backend test suite yourself** to get that final confirmation before you consider RBAC-01 fully closed out.

Every file was delivered individually with a drift check (re-stage, re-diff) immediately before each write, except where noted above; zero rejected writes on final delivery.

---

## Files Changed, Edited, or Created This Engagement

**Backend**
- `backend/db_manager.py` — added `tenants`/`users` tables and bcrypt password storage; fixed the `SELECT changes()` DuckDB-incompatibility bug in `update_user_role()`/`remove_user()`.
- `backend/accounts.py` — new real `signup`/`login`/`me` endpoints; dev-login retired (404s); team management (invite/list/role-change/remove).
- `backend/main.py` — `require_role()` gating added to ledger upload and delete.
- `backend/categorization.py` — `require_role()` gating added to category-suggestion apply.
- `backend/metrics.py` — `require_role()` gating (owner/admin) added to the three platform metrics endpoints.
- `backend/tests/conftest.py` — auth fixtures rebuilt on real account-creation functions.
- `backend/tests/test_accounts.py` — new file; full team-management test coverage.
- New RBAC test section covering role-gating on every touched endpoint (~25 checks total, combined with the above).

**Frontend**
- `frontend/components/ClientContext.tsx` — rewritten around real login/signup/session-restore instead of always-auto-authenticate dev-login.
- `frontend/components/AuthGate.tsx` — new component; gates the app behind real sign-in/sign-up.
- `frontend/components/AppShell.tsx` — shows real signed-in user email/role, working sign-out, hides Upload Ledger for viewers.
- `frontend/components/__tests__/ClientContext.test.tsx` — rewritten for the real session-restore flow.
- `frontend/components/__tests__/AssumptionLedger.test.tsx` — rewritten for the real session-restore flow.
- `frontend/components/__tests__/SubAgentWidget.test.tsx` — rewritten for the real session-restore flow.
- `frontend/components/__tests__/SwarmLogStreamer.test.tsx` — rewritten; redesigned first test to start from a genuine signed-out state.
- `frontend/components/__tests__/KnownGapsPanel.test.tsx` — rewritten for the real session-restore flow.

**DevOps / CI-CD (written, not executed)**
- `docker-compose.yml`, backend and frontend `Dockerfile`s — new, local scaffolding.
- `.github/workflows/*.yml` — new CI workflow (lint/test/build); delivered as a file for you to place by hand — protected path in this environment.
- Terraform skeleton (Vercel + Render provider resources) — new, reviewed, never run.

**Documentation**
- `docs/NexusFlow_Master_Build_List_v1.8.docx` — new this session; updates MBL-002/003/012/013/014 and AUTH-01/AUTH-02/RBAC-01/RBAC-02/TEN-01/CICD-01/BILL-01/QA-01.
- `docs/NexusFlow_Engineering_Debrief_25Aug2026.md` — this document.

---

## How to Log In

Your database has no accounts in it yet, so the sign-up form is the front door, not sign-in. On the screen you saw, use the **sign-up** side: pick a company name, your email, and a password. That call creates your tenant and your account — automatically as `owner`, the highest role — and logs you straight in; there's no separate confirmation step. From then on, use the **login** side with that same email and password. Anyone you invite afterward (via team management, once you're signed in) will show up with whatever role you assign them.
