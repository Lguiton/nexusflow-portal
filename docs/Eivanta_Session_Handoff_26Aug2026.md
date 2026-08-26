# Eivanta — Session Handoff (26 August 2026)

Written at the founder's request to close out a long session cleanly before starting a new chat. This is the single doc a new session should read first — it says what's real, what's next, and what's still blocked, without re-deriving it from the codebase.

For the full status of every backlog item, see **`Eivanta_Master_Build_List_v1.9.docx`** (this session's update) — this handoff only covers what changed and what's immediately next.

## What shipped this session (real, committed locally)

- **Full working-tree commit.** 154+ previously-uncommitted files (RBAC-01 auth, the Eivanta rebrand, Phase 6 DevOps scaffolding) are now in git — commit `3d915ba`.
- **Track 3 — persistent vector RAG knowledge base.** `backend/app/core/rag.py` rewritten: real OpenAI embeddings (BYOK-aware), real persistent Qdrant storage, every query tenant-filtered. Four new `/api/v1/knowledge/*` endpoints + `KnowledgeBaseCard.tsx`, wired into the Trust tab. Multi-format ledger ingestion extended alongside it (`.csv/.xlsx/.xls/.json/.pdf`, dispatched by real file extension).
- **Track 4 — multi-turn conversational memory.** Real `conversation_turns` persistence table; `orchestrator.route_query()` fetches session history before routing and logs both sides after. BI Engineer (`bi_engineer.generate_bi_summary`) is wired to use it in its narrative prompt. **Not yet wired:** the other 7 agent functions — same mechanical pattern, not done.
- **ENT-03 — audit/lineage log.** New `ai_lineage_log` table, SHA-256 hash-chained per tenant (real tamper evidence via `verify_lineage_chain()`, not just a claim). One entry per routed query. `GET /api/v1/audit/lineage` + a Trust-tab card.
- **FinOps budget gates (extends AI-06).** Optional per-tenant monthly USD cap (`monthly_ai_budget_usd`), real usage aggregation from the existing `ai_usage` table, and a real gate (`enforce_budget_gate`) wired into 8 AI-calling endpoints — returns a real `402` once a tenant's cap is hit. `GET/POST/DELETE /api/v1/settings/budget` + a Trust-tab card. **Not yet wired:** the knowledge-base endpoints (cheaper embeddings calls).
- **Task 59 quick win.** `ForecastCard.tsx` now calls the real, already-live `POST /api/v1/predictive/forecast` instead of showing "not wired in yet."
- **Master Build List updated to v1.9** (rebranded title, corrected two stale statuses — BYOK was already done and the doc hadn't caught up; persistent vector storage is now real — and added the two new backlog items below).

Three commits from this session sit on the **local repo only**: `60b9dae`, `02b3cae` (plus the pre-existing `3d915ba`). **Not pushed to origin** — deliberately held pending the founder's separate explicit go-ahead, since a push is more consequential/public than a local commit.

## Next up — the two items explicitly on the to-do list

### Task 57 — MCP tool server (INT-01 in the Master Build List)
Not started. Build a read-only Model Context Protocol tool server exposing the platform's analytics functions so external workflow clients (Claude Desktop, other MCP-aware tools) can query a tenant's data without custom connector code. Needs: which functions to expose read-only (BI summary, forecast, ledger rows are the obvious first candidates), and an auth story for an MCP client that isn't a logged-in browser session (a scoped API key, most likely — doesn't exist yet).

### Task 58 — SMB One-Tap Interface (UX-06 in the Master Build List)
**Blocked**, not just unstarted. An earlier session's "One-Tap SMB Interface — Corrected Design & Build List" doc defined a specific six-button-to-agent mapping table (which of the six buttons maps to which backend agent/endpoint). That table was pasted into a chat session and lost from context after a conversation compaction — deliberately **not** rebuilt from memory, since guessing the mapping would mean silently redesigning a product decision. **Needs the founder to re-share that doc (or just the six-button mapping table) before this can start.**

## Other open items, not forgotten

- **Push to origin.** Three local commits are ready; needs the founder's explicit "yes, push" before it happens.
- **BYOK rollout.** `get_openai_client_for_tenant_sync()` (the BYOK-aware per-call client pattern) is only live in `ops_shield.py` and `rag.py`'s embeddings. The other 8 agent modules (`virtual_cfo`, `bi_engineer`, `predictive_forecaster`, `report_generator`, `saas_strategist`, `data_engineer`, `bi_visualization_architect`, `external_telemetry_scout`) still use the old module-level `OpenAI(api_key=...)` singleton. Mechanical, not architecturally hard.
- **Wix marketing site (`MKT-01`, new this update).** Work so far: connected the Claude-in-Chrome browser extension, took a first look at the live Wix editor. **Domain spelling needs the founder's own verification**: the Wix editor's domain-connect banner read "**eivantra.com**" (extra "r") on close inspection, not "eivanta.com" — never resolved either way. Don't connect any domain until the founder confirms via their own Wix Domains dashboard which spelling they actually purchased. SaaS-to-site connection was explicitly deferred by the founder to a future pass.
- **Explainable-AI / FinOps gaps still open even after this update:** BYOK's live-key-validation-on-save isn't built (a bad key is only discovered at first real use); the budget gate doesn't cover the knowledge-base endpoints yet; DATA-10's embedding versioning/re-indexing isn't built.

## Where things live

- Repo: `C:\Users\Guito\nexusflow-portal` (device bridge), branch `main`, HEAD at `02b3cae` as of this handoff.
- Standing workflow: stage → edit → verify (syntax check; balance-check for TSX) → `SendUserFile` → re-verify mtime → `device_commit_files` → git commit locally. Never push without asking first.
- Authoritative backlog: `docs/Eivanta_Master_Build_List_v1.9.docx` (SRS-coded items) plus `docs/Eivanta_Improvements_and_Next_Steps_AUDITED.docx` (Track-numbered items) — the two aren't fully reconciled with each other; this session cross-referenced both where an item appeared on one but not the other.
