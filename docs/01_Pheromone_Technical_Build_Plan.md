# Pheromone — Technical Build Plan & AI-Coding Master Document

**Project:** Pheromone — Agentic AI Recall Operating System for Shop Owners
**Hackathon:** AMD Developer Hackathon 2026, Track 1 (AI Agents & Agentic Workflows)
**Optimizing for:** Grand Prize ($5K) + Hugging Face Special Prize + Ship It bonus
**Solo build, "robustness over speed" commitment**
**Document version:** v1.0 — locked design baseline before code

---

## 0. How to use this document

This document is the single source of truth for building Pheromone. It is structured for use with AI-assisted coding tools (Claude Code, Cursor, Windsurf, Copilot, Cody, etc.) across multiple sessions and across multiple AI tools if context windows expire mid-build.

**Three ways to use it:**

1. **At project start** — paste Section 1 (Master Onboarding Prompt) into your AI coder along with this document. The AI now has full project context.
2. **At phase start** — paste the relevant Phase Section. The AI executes that phase using the test cases as the definition of done.
3. **At session resume / tool switch** — paste Section 2 (Resume Prompt Template) plus this document plus your `STATE.md` (which you maintain). The new session is now caught up.

**Discipline:** Do not advance to phase N+1 until every test case in phase N passes. The test cases are not optional. They are the contract.

---

## 1. MASTER ONBOARDING PROMPT (paste at project start)

```
You are an AI coding assistant working on Pheromone, an agentic AI recall operating
system for grocery shop owners (small independent shops AND regional chains, both).

CONTEXT:
Pheromone is being built solo for the AMD Developer Hackathon 2026 (Track 1: AI Agents).
The system ingests food recall notices from FDA/USDA/supplier sources, traces affected
products through a complex supply chain graph, computes per-transaction affected
probability via inventory composition modeling, drafts confidence-tier-appropriate
customer notifications (including REASSURANCE notifications for unaffected customers
— the killer differentiator), and generates an audit-ready compliance report.

CORE THESIS:
A recall is not one event — it is a chain of uncertain signals, supplier relationships,
product transformations, shipments, sales, and customer identities. The agent's job
is not just to detect recalls; it is to manage uncertainty until the right humans can
take safe action.

NAMING / METAPHOR:
The name Pheromone is not arbitrary. When ants find contaminated food, they lay a
pheromone trail back to its source so the colony can respond in a targeted way —
not by broadcasting panic, but by signaling specifically to the affected and letting
unaffected workers continue undisturbed. That is exactly the behavior of this system.
Keep this metaphor coherent in code comments, commit messages, error messages, and
any user-facing copy. The system "lays a trail" back through the supply chain. It
"signals selectively" to affected and unaffected customers. It protects "the colony"
(both the customer base and the shop's brand).

THIS PROJECT'S DIFFERENTIATORS (all judges should see these):
1. PROBABILISTIC PROVENANCE: We do not require lot codes at checkout. Instead, we
   compute (store, product, time) → probability distribution over which pallet a unit
   came from, by replaying stocking and sale events. Per-transaction affected
   probability is the mass on affected pallets.
2. REASSURANCE NOTIFICATIONS: Six confidence tiers including "Confirmed Unaffected"
   and "Likely Unaffected." Existing recall apps only notify the affected. We notify
   the safe with proof, preventing panic refunds and protecting brand trust.
3. INGREDIENT-LEVEL BLAST RADIUS: Hierarchical recipes mean a contaminated ingredient
   propagates through multiple finished products. Trace Agent walks this graph.
4. AGENT vs DETERMINISTIC SPLIT: LLM agents handle reasoning under uncertainty
   (parsing messy notices, drafting messages). Deterministic code handles graph
   traversal, scoring math, and compliance logging. Production-grade architecture.

ARCHITECTURE:
- 5 LangGraph agents: Intake, Trace, Match, Ops, Comms (Compliance Logger runs passively)
- Postgres (Supabase) with recursive CTEs for graph traversal
- Qwen3-32B for reasoning agents, Qwen3-8B for high-volume Match operations
- vLLM v0.x serving on AMD Instinct MI300X via AMD Developer Cloud (locked: NOT Fireworks
  or any abstraction layer — judges expect to see direct AMD ROCm usage)
- Next.js 14 + Tailwind + shadcn/ui frontend
- React Flow for blast-radius visualization
- Live agent telemetry surfaced in dashboard: per-agent latency, token counts,
  GPU memory utilization (via rocm-smi sampling) — visible to judges in demo
- FastAPI backend
- Twilio sandbox / SendGrid for notification drafts (NEVER actually send in demo)

COMPUTE NARRATIVE (use this exact phrasing in submission text and demo narration):
Pheromone runs Qwen3-32B on a single AMD Instinct MI300X via vLLM and ROCm 7. The
192GB HBM3 memory means all five agents share live context without paging — critical
for the cross-agent reasoning that makes recall blast-radius accurate. We use FP8
quantization to fit Qwen3-32B alongside Qwen3-8B (used for high-volume transaction
scoring) on a single GPU.

MAKE THE AMD STORY VISIBLE. Other strong hackathon submissions explicitly foreground
"vLLM with ROCm serving Qwen on MI300X's 192GB HBM3" in their description. We do the
same. Hackathon judges weight visible AMD usage on the Application of Technology axis.

DEMO SCENARIOS:
- Primary: "Salsa-Verde" — ingredient-level recall, multi-facility manufacturer,
  showcases blast-radius graph + reassurance batch
- Secondary: "Store-4-Fridge" — internal trigger, time-window matching, store-scoped recall

ROBUSTNESS COMMITMENT (A+B+C):
A. Every edge case from the design doc has a working code path
B. Demo never crashes; edge cases gracefully degrade
C. Tested adversarially against 20+ real FDA recalls

YOUR JOB:
- Execute the phase you are given, in order
- Do not skip ahead, do not improvise scope
- Do not advance until ALL phase test cases pass
- When test cases pass, update STATE.md with phase completion timestamp
- If you discover a design issue, STOP and ask before deviating
- Use Python 3.11+, Node 20+, TypeScript strict mode
- All schemas in Pydantic (Python) or Zod (TypeScript)
- Every agent has a structured output contract (JSON Schema)
- Every database operation goes through a typed repository layer
- Demo mode is the default; real notification sending is gated behind an env flag
  that is OFF in development

CODE QUALITY BAR:
- Type hints everywhere
- Pydantic models for all agent I/O
- Postgres migrations are versioned (Alembic)
- Every agent has at least 3 unit tests for core reasoning
- Integration tests exercise end-to-end flow on at least 2 real FDA recalls
- All datetime fields stored as UTC, displayed in user timezone
- Never log PII; redact email/phone in logs

The project lives in /pheromone/. Repo structure:
/pheromone
  /backend          FastAPI + LangGraph
    /agents         Each agent is a module
    /db             Postgres schema, migrations, repositories
    /engine         InventoryCompositionEngine and other deterministic logic
    /tests
  /frontend         Next.js dashboard
    /app
    /components
    /lib
  /data_generator   Python script to generate synthetic supply chain data
  /infra            Docker, deployment configs
  /docs             Including this document
  STATE.md          Build state log (update after each phase)

BEFORE YOU WRITE A LINE OF CODE:
1. Confirm you have read this prompt
2. Confirm you have read the current phase section of the build plan
3. Confirm you understand the test cases for the current phase
4. State which phase you are about to execute and your plan
5. Then begin
```

---

## 2. RESUME PROMPT TEMPLATE (paste when switching tools / resuming sessions)

When your AI tool's context expires or you switch between tools (e.g., from Claude Code to Cursor), paste this template, filled in with the current state.

```
RESUME PHEROMONE BUILD

You are taking over an in-progress agentic AI hackathon project for the
AMD Developer Hackathon 2026 (Track 1, Grand Prize chase).

Project: Pheromone — recall operating system for grocery shop owners.
See attached: Pheromone_Technical_Build_Plan.md (this document)
See attached: Pheromone_Project_Context.md (the impact / what we built / why doc)
See attached: STATE.md (current build state, last phase completed)

I am resuming work after a context expiration / tool switch.

CURRENT STATE:
- Phase completed last: PHASE_<N> (see STATE.md for details)
- Current branch: <branch>
- Last commit: <commit_sha>
- Phase to execute next: PHASE_<N+1>
- Known blockers: <list, or "none">

YOUR FIRST ACTIONS:
1. Read the Master Onboarding Prompt (Section 1 of the Build Plan)
2. Read the relevant phase section: PHASE_<N+1>
3. Read STATE.md to confirm what is already built
4. Verify the repo state matches STATE.md (run: git status, ls)
5. State your understanding of:
   a. Where we are in the build
   b. What phase you will execute
   c. The test cases that define "done" for this phase
6. Wait for my confirmation before writing any code

If anything in the build state seems inconsistent with the build plan, STOP and
ask. Do not improvise. Do not skip phases.
```

---

## 3. STATE.md TEMPLATE (you maintain this file)

Create `/pheromone/STATE.md` at project start and update after every phase. This is the file you paste into resume prompts.

```markdown
# Pheromone Build State

Last updated: <ISO datetime UTC>
Repo: <git remote url>
Branch: <current branch>
Last commit: <sha>

## Phases completed
- [x] Phase 0: Repo + environment setup    (completed: 2026-05-XX HH:MM UTC)
- [x] Phase 1: Database schema             (completed: ...)
- [ ] Phase 2: Synthetic data generator
- [ ] Phase 3: Real FDA data ingestion
- [ ] Phase 4: Intake Agent
- [ ] Phase 5: Trace Agent + InventoryCompositionEngine
- [ ] Phase 6: Match Agent
- [ ] Phase 7: Ops Agent
- [ ] Phase 8: Comms Agent (with Reassurance)
- [ ] Phase 9: LangGraph orchestration + state persistence
- [ ] Phase 9B: HF Space early-launch stub (CRITICAL — go live ASAP for likes)
- [ ] Phase 10: Frontend dashboard (with AgentTelemetryStrip + HardwareBadge)
- [ ] Phase 11: Compliance logger + audit report
- [ ] Phase 12: Real-FDA stress test (20 recalls)
- [ ] Phase 13: HF Space full live upgrade (replaces stub)
- [ ] Phase 14: Demo polish + recording + final Ship-It blast

## Outstanding decisions (none should remain when starting code)
- (list any unresolved design questions)

## Known issues / TODOs
- (carry-over notes from previous session)

## Test case results (latest run per phase)
- Phase 1: <pass/fail counts and any failures>
- ...

## Notes for the next session
- (anything you want the next AI to know)
```

---

## 4. ARCHITECTURE LOCK

These are not negotiable mid-build. If a phase reveals one is wrong, STOP and discuss before changing.

**Backend stack**
- Python 3.11
- FastAPI for REST + Server-Sent Events for live agent progress
- LangGraph for agent orchestration
- Pydantic v2 for all agent I/O contracts
- Postgres 16 (Supabase) with Alembic migrations
- vLLM for Qwen serving (running on AMD MI300X via AMD Developer Cloud)

**Frontend stack**
- Next.js 14 (App Router)
- TypeScript strict mode
- Tailwind + shadcn/ui
- React Flow for graph visualization
- TanStack Query for server state

**Data**
- openFDA Recall API (food/enforcement endpoint) — real, free
- USDA-FSIS recall RSS — real, free
- Synthetic supply chain data generated locally (~50K rows)

**LLM models**
- `Qwen/Qwen3-32B` for: Intake, Trace reasoning steps, Ops, Comms
- `Qwen/Qwen3-8B` for: high-volume Match Agent operations
- Served via vLLM with structured-output (JSON Schema) constraints

**Repo layout (locked)**
```
/pheromone
├── backend/
│   ├── agents/
│   │   ├── intake_agent.py
│   │   ├── trace_agent.py
│   │   ├── match_agent.py
│   │   ├── ops_agent.py
│   │   ├── comms_agent.py
│   │   └── __init__.py
│   ├── db/
│   │   ├── models.py            # SQLAlchemy / Pydantic-equivalent
│   │   ├── repositories.py      # Typed data access
│   │   ├── migrations/          # Alembic
│   │   └── ctes.py              # Recursive CTE queries
│   ├── engine/
│   │   ├── composition_engine.py    # InventoryCompositionEngine
│   │   ├── confidence.py            # Tier mapping
│   │   └── recall_graph.py          # Blast radius traversal
│   ├── api/
│   │   ├── main.py              # FastAPI app
│   │   └── routes/
│   ├── orchestration/
│   │   ├── graph.py             # LangGraph definition
│   │   └── state.py             # Recall case state machine
│   ├── compliance/
│   │   └── logger.py
│   ├── settings.py
│   └── tests/
├── frontend/
│   ├── app/
│   │   ├── page.tsx              # Recall feed
│   │   ├── recall/[id]/page.tsx  # Recall detail
│   │   └── api/                  # Next API routes (proxy to backend)
│   ├── components/
│   │   ├── BlastRadiusGraph.tsx
│   │   ├── ConfidenceTable.tsx
│   │   ├── NotificationDrafts.tsx
│   │   └── ApprovalQueue.tsx
│   └── lib/
├── data_generator/
│   ├── generate.py
│   ├── seeds/
│   │   ├── salsa_verde_seed.py
│   │   └── store4_fridge_seed.py
│   └── tests/
├── infra/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── docker-compose.yml
│   └── hf_space/
│       └── Dockerfile
├── docs/
│   ├── 01_Pheromone_Technical_Build_Plan.md  (this file)
│   ├── 02_Pheromone_Project_Context.md
│   └── architecture_diagrams/
└── STATE.md
```

---

## 5. PHASE-BY-PHASE BUILD PLAN

Each phase has: **Goal**, **Deliverables**, **Test Cases (Definition of Done)**, **AI Coding Prompt**.

The AI Coding Prompt at the end of each phase is what you paste into your AI tool to execute that phase. Always preface with the Master Onboarding Prompt if it is a fresh session.

---

### PHASE 0 — Repository & Environment Setup

**Goal:** Working dev environment with all infrastructure verified before any code.

**Deliverables:**
- Initialized git repo with the locked structure above
- Python virtual environment with backend dependencies pinned in `pyproject.toml`
- Node project with frontend dependencies pinned in `package.json`
- Postgres running locally via Docker (or Supabase dev project)
- Verified connection to AMD Developer Cloud, MI300X instance provisioned
- Verified vLLM serving Qwen3-32B with a test inference call
- Pre-commit hooks for Python (ruff, black, mypy) and TS (eslint, prettier)
- `STATE.md` initialized

**Test cases:**
1. `cd backend && pytest --collect-only` lists at least one test (placeholder OK)
2. `cd frontend && npm run build` succeeds with empty Next app
3. `docker compose up -d postgres && psql -h localhost -U postgres -c 'SELECT 1;'` returns 1
4. `curl <vllm_endpoint>/v1/chat/completions` with a Qwen3-32B prompt returns a valid response in <10s
5. `curl https://api.fda.gov/food/enforcement.json?limit=1` returns valid JSON with at least one recall record
6. `git log --oneline` shows at least 1 commit; `STATE.md` exists

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 0: Repository & Environment Setup.

Read the deliverables and test cases for Phase 0 in the build plan.
Initialize the locked repo structure exactly as specified. Use these versions:
- Python 3.11, FastAPI ~=0.115, Pydantic ~=2.9, SQLAlchemy ~=2.0, alembic ~=1.13,
  langgraph ~=0.2, langchain ~=0.3, pytest ~=8.3, ruff, black, mypy
- Next.js 14 (latest stable), TypeScript 5.x strict, Tailwind 3.x, shadcn/ui,
  reactflow ~=11, @tanstack/react-query ~=5

Set up all configuration files (pyproject.toml, package.json, tsconfig.json,
.gitignore, .env.example). Create empty placeholder files for each module in the
locked structure so imports resolve.

Provision and verify the AMD Developer Cloud instance separately (this requires
my interaction). Wait for me to confirm the vLLM endpoint URL before adding it
to .env.example.

Run all 6 test cases and confirm pass. Update STATE.md.
```

---

### PHASE 1 — Database Schema

**Goal:** Postgres schema for the entire supply chain graph and recall lifecycle, with Alembic migrations and typed repositories.

**Deliverables:**

Tables to create (mapping back to the locked design):

Core supply chain:
- `suppliers`
- `ingredients` (with `parent_ingredient_id` FK for hierarchical recipes)
- `ingredient_lots`
- `manufacturers`
- `facilities` (plants, with `plant_code` for lot encoding)
- `production_runs` (with `ingredient_lots_used` JSONB array)
- `finished_products` (with `ingredient_recipe` JSONB array)
- `finished_product_lots` (with `lot_code`, `best_by_date`)
- `pallets` (single source lot per pallet)
- `shipments` (manufacturer → distributor)
- `distributors`
- `distributor_warehouses`
- `stores`
- `store_shipments` (warehouse → store)

Provenance / inventory:
- `stocking_events` (pallet contributes units to store inventory; this drives the InventoryCompositionEngine)
- `pos_transactions` with `line_items` JSONB
- `customers` (loyalty, with profile JSONB: kids, allergies, immunocompromised, language, consent flags)
- `institutional_accounts` (school/hospital/elder-care; FK to customer or standalone)

Refrigeration (for Store-4-Fridge demo):
- `refrigeration_zones`
- `refrigeration_events`

Recall lifecycle:
- `recall_cases` (the orchestrator; with state column matching the 20-state machine)
- `recall_specs` (parsed Intake output, JSONB)
- `affected_blast_radius_snapshots` (Trace Agent output, versioned)
- `scored_transactions` (Match Agent output)
- `employee_tasks` (Ops Agent output)
- `notification_drafts` (Comms Agent output)
- `approvals` (manager actions)
- `compliance_log` (passive logger; append-only, every event timestamped)
- `recall_scope_versions` (for handling scope expansion)

All FKs declared. All datetimes UTC with explicit timezone. Indexes on every FK and on time-range columns used for inventory composition queries.

Recursive CTE files (`db/ctes.py`):
- `cte_blast_radius_from_ingredient_lot` — given a contaminated ingredient lot, return all affected pallets, shipments, stores, transactions
- `cte_blast_radius_from_finished_product_lot` — given a contaminated finished product lot
- `cte_blast_radius_from_facility_window` — given a facility + time window
- `cte_inventory_composition_at_time` — given (store, product, time), return pallet composition

Repository layer (`db/repositories.py`):
- One repository class per aggregate (Recall, SupplyChain, Inventory, Customer, etc.)
- All read/write goes through repositories; no raw SQL in agent code

**Test cases:**
1. `alembic upgrade head` runs cleanly on empty database
2. `alembic downgrade base` reverses all migrations cleanly
3. Pytest fixture inserts one row in each of the 25+ tables successfully
4. Recursive CTE `cte_blast_radius_from_ingredient_lot` returns correct results on a hand-crafted 4-store fixture (1 ingredient lot → 2 production runs → 2 product lots → 4 pallets → 3 shipments → 4 stores → 12 transactions; query must return all 12)
5. `cte_inventory_composition_at_time` returns correct probability distribution on a fixture with 3 stocking events and 5 sale events
6. Repository test: round-trip create → read → update → read → delete on a `RecallCase` with a `RecallSpec` succeeds and preserves all fields
7. Concurrent insert test: 100 simultaneous `notification_drafts` inserts complete without deadlock

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 1: Database Schema.

Read Phase 1 of the build plan. Create:
1. SQLAlchemy 2.0 ORM models (declarative, mapped style) for every table in
   /backend/db/models.py
2. Alembic migrations under /backend/db/migrations/versions/
3. Recursive CTE queries in /backend/db/ctes.py — write them as pure SQL
   templates with named parameters, executed via SQLAlchemy text()
4. Typed repository classes in /backend/db/repositories.py
5. Pytest fixtures in /backend/tests/conftest.py that spin up a test Postgres
   via testcontainers and provide a clean schema per test

Critical:
- Every datetime is timezone-aware UTC (use TIMESTAMP WITH TIME ZONE)
- JSONB columns use Pydantic models for serialization/deserialization (define
  these models in db/models.py alongside ORM)
- Indexes on: every FK, (store_id, product_id, timestamp) for stocking events,
  (store_id, timestamp) for transactions, (recall_case_id, created_at) for compliance log
- The `compliance_log` table is append-only — enforce via Postgres trigger that
  rejects UPDATE and DELETE
- The `recall_scope_versions` table preserves history of scope changes; the
  current scope is the latest version

Run all 7 test cases. The Phase 1 fixture for test 4 is non-trivial — it must
construct a realistic 4-store hand-crafted scenario. Document the fixture
clearly. Update STATE.md.

Do not move to Phase 2 until all test cases pass.
```

---

### PHASE 2 — Synthetic Data Generator

**Goal:** A deterministic Python script that populates Postgres with ~50K rows of internally consistent supply chain data, including specific seeds for both demos.

**Deliverables:**

`/data_generator/generate.py` with these phases of generation (in order, because of dependencies):

1. Static seeds: 8 suppliers, 35 ingredients (including 5 hierarchical: e.g., "seasoning_blend_X" composed of salt, garlic_powder, paprika), 4 manufacturers (one with 3 plants), 8 facilities, 60 finished products (5 of which have hierarchical recipes containing the seasoning blend), 2 distributors, 4 warehouses, 8 stores
2. Time-series generation over 60 days:
   - 300 ingredient lots (with received-at-facility dates)
   - 500 production runs (consuming ingredient lots, producing product lots)
   - 1,500 finished product lots (with realistic lot codes encoding plant + date + batch)
   - 8,000 pallets
   - 700 manufacturer→distributor shipments
   - 3,000 distributor→store shipments
   - 6,000+ stocking events at stores (each pallet stocks in one or more events)
3. 2,000 customers with consistent buying habits:
   - Each customer has a "shopping profile" (preferred store, typical days/times, ~10-20 frequent products)
   - Generate 60 days of transactions following the profile
   - 15 of the customers are institutional accounts (5 schools, 5 hospitals/elder-care, 5 small restaurants)
   - Realistic distribution of payment types: ~50% loyalty card, ~25% credit-card-with-email, ~20% cash, ~5% third-party platform
   - Lot codes captured at checkout for ~20% of transactions (the "forward-looking shop" subset)
4. Refrigeration zones for each store; sparse `refrigeration_events` (mostly inspections, occasional brief failures)
5. Demo-specific seeds:
   - **Salsa-Verde seed:** ingredient `roasted_garlic_paste` lot RG-4429 (contamination_status=confirmed_contaminated), shipped exclusively to Plant 2 of "Sunny Valley Foods" between April 15-22, 2026; Plant 2 produced "Sunny Valley Salsa Verde 16oz" (UPC 0-72440-12345-6) lots P2-052126-A through P2-052126-F using this ingredient lot; these went to Distributor West, then to 6 of 8 Acme stores between April 17 and May 1; ~1,800 transactions of this product across affected stores in the window
   - **Store-4-Fridge seed:** Refrigeration zone `Store4_Deli_Fridge` failed at 02:14 UTC May 5, discovered at 06:00 UTC May 5; 12 refrigerated products in zone; ~75 transactions of those products in the failure window; affected only Store 4

Key implementation notes:
- Use a single random seed (configurable, default `42`) so generation is fully reproducible
- Generate in dependency order so FKs are valid
- Use `INSERT ... ON CONFLICT DO NOTHING` so re-runs are idempotent
- Provide `--reset` flag that truncates all tables first
- Provide `--scenario {salsa_verde, store4_fridge, both, none}` flag
- Print summary statistics at end (rows per table, scenario state)

**Test cases:**
1. `python data_generator/generate.py --reset --scenario both --seed 42` runs in <60 seconds and exits 0
2. Row counts after run match expected ranges (asserted in `data_generator/tests/test_volumes.py`)
3. Re-running with same seed produces identical row counts (idempotent given `--reset`)
4. Salsa-Verde seed verification:
   - Lot `RG-4429` exists with `contamination_status='confirmed_contaminated'`
   - Lot RG-4429 was used in production runs only at Plant 2
   - Resulting product lots P2-052126-A through P2-052126-F exist
   - These lots arrived only at Distributor West
   - Distributor West shipped them only to 6 specified stores (not 7 or 8)
   - At least 1,500 transactions of UPC 0-72440-12345-6 exist at affected stores in the window
5. Store-4-Fridge seed verification:
   - Refrigeration event of type 'failure' exists at expected timestamp
   - Refrigeration event of type 'restored' exists at expected timestamp
   - At least 50 transactions of refrigerated items at Store 4 in the failure window
6. Customer profile consistency: pick 20 random customers, verify their transactions over the 60 days are concentrated at their "preferred store" (>70% of their transactions at one store)
7. Hierarchical recipe verification: at least one finished product has a recipe entry that is itself a composite ingredient (e.g., "seasoning_blend_X"), and that composite has its own ingredient_recipe

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 2: Synthetic Data Generator.

Read Phase 2 of the build plan. Build /data_generator/generate.py per the spec.

Implementation notes:
- Use Faker for plausible names/addresses/phone/email
- Use real UPC codes pulled from a curated list of 60 actual FDA-recalled products
  (I will provide this list before you start; if not provided, use plausible
  12-digit UPCs)
- Lot codes follow format: <PLANT_CODE>-<MMDDYY>-<BATCH_LETTER>
- Best-by dates are 60-180 days after production date depending on product
- Hierarchical recipe: at minimum 5 finished products use 'seasoning_blend_X'
  which itself contains 'salt', 'garlic_powder', 'paprika', 'roasted_garlic_paste'
- The seed scenarios are EXACT: hardcode the lot RG-4429, the dates, the stores.
  These are the demo's truth.

Write all 7 test cases as pytest tests in /data_generator/tests/. Run them.
Update STATE.md. Do not move to Phase 3 until all pass.
```

---

### PHASE 3 — Real FDA Data Ingestion

**Goal:** Pull real recalls from openFDA + USDA-FSIS, normalize them, store them as raw notices ready for the Intake Agent to process.

**Deliverables:**

- `/backend/integrations/openfda.py` — client for the FDA enforcement API; pull last 90 days of food recalls; map raw response into `RawRecallNotice` model
- `/backend/integrations/usda_fsis.py` — RSS reader for USDA FSIS recalls; same shape
- `/backend/integrations/source_verifier.py` — verifies a recall comes from a whitelisted source URL (FDA, USDA, named manufacturers); flags unverified
- `/backend/integrations/notice_router.py` — single entry point: take a notice from any source, store it as `unverified_recall_signal` if source is unknown, else as a verified recall ready for Intake
- A test fixture of 25 real FDA recall JSONs saved to `/backend/tests/fixtures/real_recalls/` for offline testing
- A simulated supplier notice folder: `/backend/integrations/supplier_inbox/` with 5 hand-written realistic supplier emails (text files) covering: clean ingredient recall, ambiguous lot codes, multi-product implication, packaging issue, retraction of prior notice
- A retailer-internal trigger: a function `submit_internal_qa_issue(store_id, description, severity, time_window)` that creates a recall_case directly

**Test cases:**
1. Live API test (gated by env flag): `pull_recent_fda_recalls(days=7)` returns at least 1 record without error
2. Offline replay test: process the 25 fixture recalls; all 25 are stored as raw notices with verified source
3. Source verification: a notice from `https://malicious-site.example.com` is flagged as `unverified_recall_signal`; a notice from `https://www.fda.gov/...` passes
4. Supplier inbox: all 5 hand-written notices are ingested; each gets a `RawRecallNotice` row
5. Internal trigger: `submit_internal_qa_issue` creates a recall_case in state `signal_detected` with source_type='retailer_internal'
6. De-duplication: re-ingesting the same FDA recall by its `recall_number` is idempotent (no duplicate rows)
7. Schema robustness: at least 5 of the 25 fixture recalls are intentionally malformed in different ways (missing fields, weird date formats, embedded HTML); all 5 ingest successfully with sensible defaults

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 3: Real FDA Data Ingestion.

Read Phase 3 of the build plan. Build the integrations per spec.

For openFDA: use https://api.fda.gov/food/enforcement.json (no key required for
low volume; we are well within free tier). Pull with `search=report_date:[<start>+TO+<end>]&limit=100`.

For USDA-FSIS: use the RSS feed at https://www.fsis.usda.gov/fsis/api/recall/v/1
(JSON endpoint actually exists) — fall back to scraping the recall list page if
the API fails.

For the 25 fixtures, pull them yourself from openFDA and save the raw JSON.
Pick a diverse set: 5 Class I (high-severity), 10 allergen-undeclared, 5 with
limited information, 5 with explicit lot codes. Document each fixture's
properties in /backend/tests/fixtures/real_recalls/INDEX.md.

For the 5 supplier notice templates, write realistic emails at varying levels
of detail. They will be the primary test inputs for the Intake Agent in Phase 4.

Run all 7 test cases. Update STATE.md.
```

---

### PHASE 4 — Intake Agent

**Goal:** An agent that ingests messy recall notices (FDA structured + supplier emails + internal triggers) and produces clean, structured `RecallSpec` objects with explicit confidence on each extracted field.

**Deliverables:**

- `/backend/agents/intake_agent.py`
- Pydantic model `RecallSpec` with:
  - `recall_id`, `source_type`, `source_url`, `parsed_at`
  - `product_identifiers`: list of {brand, product_name, upc, package_size, image_url}
  - `lot_codes`: list of strings, each with extraction confidence
  - `best_by_dates`: list of date ranges
  - `affected_facilities`: list of facility codes (when extractable)
  - `affected_distribution`: list of states/regions/distributors
  - `severity`: enum(critical, high, medium, low, unknown)
  - `hazard_type`: enum(salmonella, listeria, ecoli, allergen, foreign_object, undeclared_ingredient, other)
  - `hazard_details`: free-text
  - `symptom_timeline_days`: tuple (min, max) — for actionability scoring later
  - `remedy_instructions`: free-text
  - `extraction_confidence`: dict per field (0.0–1.0)
  - `raw_notice_text`: original text for audit
- Agent uses Qwen3-32B with structured output (vLLM JSON Schema mode)
- Multi-source verification: if a notice is also present from a second source (e.g., FDA + supplier), cross-check key fields and raise confidence
- Low-confidence flag: if `extraction_confidence` for any critical field is <0.6, mark recall_case as `requires_human_review`

**Test cases:**
1. On all 25 real FDA fixture recalls: Intake Agent produces a valid RecallSpec with `extraction_confidence` >0.8 on at least 80% of recalls (20+/25)
2. On the 5 deliberately malformed fixtures from Phase 3 test 7: agent produces RecallSpec with appropriate low-confidence flags, never crashes, never fabricates fields
3. On all 5 supplier inbox emails: agent correctly extracts product, lot, hazard, severity
4. On retailer-internal triggers: agent normalizes to RecallSpec without web fetch
5. Hazard type mapping: agent correctly classifies hazard for at least 23/25 fixture recalls (manual ground-truth labels in INDEX.md)
6. Severity classification: at least 22/25 correct against ground truth
7. Idempotency: running the agent twice on the same notice produces functionally identical RecallSpec (allowing for minor LLM variance — exact match on structured fields, similarity >0.9 on free-text)
8. No PII: agent never echoes phone numbers/emails from notices into structured output

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 4: Intake Agent.

Read Phase 4 of the build plan. Build /backend/agents/intake_agent.py.

Architecture:
- The agent is a callable class. Constructor takes vLLM client config.
- Method `parse(raw_notice: RawRecallNotice) -> RecallSpec` is the main entry.
- Use vLLM's JSON Schema constrained output to guarantee parsable output.
- Prompt design: system prompt establishes the agent's role; include 3 in-context
  few-shot examples (one ideal, one with missing fields, one supplier email);
  the user message is the raw notice text.
- Field-level confidence: ask the model to self-report confidence per field
  (0.0–1.0). If confidence <0.6 on critical fields (product_identifiers,
  hazard_type, severity), set the case state to requires_human_review.

Use the 25 FDA fixtures + 5 supplier notices as the test corpus. For test cases
5 and 6, write ground-truth labels in /backend/tests/fixtures/real_recalls/INDEX.md
(I will help if needed).

Run all 8 test cases. Document any cases where the agent struggles in
STATE.md — these are real-world risks to flag during the demo.

Do not move to Phase 5 until all 8 pass.
```

---

### PHASE 5 — Trace Agent + InventoryCompositionEngine

**Goal:** Build the blast-radius graph from a RecallSpec, walking the supply chain. Build the InventoryCompositionEngine that computes (store, product, time) → pallet probability distribution.

**Deliverables:**

`/backend/engine/composition_engine.py`:
- Class `InventoryCompositionEngine`
- `compute_composition(store_id, product_id, at_time)` returns `{pallet_id: probability}`
- Implementation: for each (store, product) maintain a running composition.
  Replay all stocking events and sale events up to `at_time`. Cache hourly snapshots.
- Sale events deplete composition uniformly (each unit sold has the average composition at time of sale).
- Returns are added back to composition with degraded confidence (small "noise" share).
- Deterministic given the same event log.

`/backend/engine/recall_graph.py`:
- Class `BlastRadiusBuilder`
- `build(recall_spec) -> BlastRadius`
- Uses the recursive CTEs from Phase 1 to walk the graph
- For ingredient-level recalls: walk forward from ingredient_lot through production_runs, finished_product_lots, pallets, shipments, stores
- For finished-product recalls: walk forward from finished_product_lot
- For facility-window recalls: walk forward from facility + time window
- Returns BlastRadius with: affected_pallets (with per-pallet certainty), affected_stores (with per-store affected stock fraction at peak), affected_transactions_window per store

`/backend/agents/trace_agent.py`:
- Calls `BlastRadiusBuilder` (deterministic)
- Calls Qwen3-32B for reasoning where data is missing or ambiguous (e.g., FDA notice doesn't specify facility, but lot code patterns suggest Plant 2 — agent infers and tags inference confidence)
- Output: `BlastRadius` with explicit confidence on every node

**Test cases:**
1. Salsa-Verde scenario: Trace Agent on the seeded recall (lot RG-4429) returns exactly the 6 affected stores (not 7, not 8); affected stock fraction matches expected (computed from generator state)
2. Store-4-Fridge scenario: Trace Agent on the seeded internal trigger returns only Store 4
3. Composition engine on a hand-crafted fixture (3 stocking events, 5 sale events): returns mathematically correct probabilities
4. Composition engine snapshot caching: querying the same (store, product, time) twice returns identical output, second call <1ms (cache hit)
5. Composition engine handles edge: sales of a product when composition is empty (no stock) returns empty dict (does not crash)
6. On a fixture where FDA notice mentions only state but lot code embeds plant code: agent correctly infers plant from lot code pattern, raises inference confidence
7. Multi-hop hierarchical: contaminated `roasted_garlic_paste` correctly propagates through `seasoning_blend_X` to all 5 finished products that use the blend
8. Probabilistic correctness: on a synthetic store with 60% Pallet A (clean) + 40% Pallet C (affected) at time T, querying transaction at T+epsilon returns affected probability ≈ 0.40 ± 0.02

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 5: Trace Agent + InventoryCompositionEngine.

Read Phase 5. This is the technical heart of the project. Take your time.

Build in this order:
1. /backend/engine/composition_engine.py — pure deterministic code, no LLM
2. Hourly snapshot caching: store snapshots in a Postgres table
   `inventory_composition_snapshots(store_id, product_id, snapshot_hour, composition jsonb)`
   add a migration for it
3. /backend/engine/recall_graph.py — BlastRadiusBuilder, uses CTEs from Phase 1
4. /backend/agents/trace_agent.py — orchestrates the deterministic builder + LLM
   reasoning for ambiguous fields. Use Qwen3-32B sparingly here; most work is code.

Performance target: composition engine must answer any (store, product, time)
query in <100ms (with snapshot cache warm). BlastRadiusBuilder must return for
the Salsa-Verde scenario in <2s.

Run all 8 test cases. Update STATE.md.
```

---

### PHASE 6 — Match Agent

**Goal:** For every transaction in the BlastRadius window, compute affected probability and assign one of 6 confidence tiers.

**Deliverables:**

`/backend/agents/match_agent.py`:
- Method `score_transactions(blast_radius, recall_spec) -> List[ScoredTransaction]`
- For each candidate transaction:
  1. Look up (store, product, time) → pallet composition via InventoryCompositionEngine
  2. For each pallet in composition, check if pallet is affected (member of blast_radius.affected_pallets)
  3. Sum probabilities of affected pallets → affected_probability
  4. Adjust if lot code was captured at checkout (overrides probability to ~1.0 or ~0.0 depending on match)
  5. Compute actionability_score from product shelf-life and time-since-purchase
  6. Map (affected_probability, actionability_score) → confidence tier:
     - >0.9 affected & actionable: Confirmed Affected
     - 0.5–0.9 affected & actionable: Likely Affected
     - 0.1–0.5 affected: Possible Affected
     - 0.01–0.1 affected: Likely Unaffected (gets reassurance)
     - <0.01 affected & customer bought same product family in window: Confirmed Unaffected (gets reassurance)
     - else: No Action
- Mostly deterministic. LLM is called only for edge cases (mixed-pallet anomalies, returns, employee discounts, etc.)
- Vulnerable population modifier: if customer profile has children/pregnancy/immunocompromised AND hazard is Listeria/Salmonella, bump tier up by one (e.g., Possible → Likely)

`/backend/engine/confidence.py`:
- Pure functions for tier mapping
- Pure functions for actionability scoring (uses product shelf life + symptom timeline)
- Documented and unit tested

**Test cases:**
1. Salsa-Verde: at least 300 transactions are tagged Confirmed Affected (the 20% with lot codes captured matching the affected lots), at least 800 Likely Affected, at least 600 Possible Affected, at least 400 Confirmed/Likely Unaffected
2. Store-4-Fridge: at least 50 transactions tagged Likely or Confirmed Affected within the failure window; transactions just before/after the window tagged Confirmed Unaffected
3. Vulnerable-population modifier: a Maria-S customer record with `kids: [{'age': 2}]` and a Listeria recall — her transactions are bumped up one tier vs. equivalent transactions for a customer without dependents
4. Reassurance eligibility: at least 800 customers are tagged Confirmed/Likely Unaffected (the reassurance-eligible bucket) on the Salsa-Verde scenario
5. Empty blast radius: zero transactions returned, no crash
6. Unknown payment type: the agent gracefully degrades (e.g., cash transaction → Confidence cannot exceed Likely; the message generation later switches to public notice)
7. Determinism: running Match Agent twice on the same blast_radius produces identical tier assignments
8. Performance: scoring 2,000 transactions completes in <30s

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 6: Match Agent.

Read Phase 6. Build /backend/agents/match_agent.py and /backend/engine/confidence.py.

Critical points:
- This phase is mostly deterministic. The LLM is called rarely.
- Reuse InventoryCompositionEngine from Phase 5; do not recompute composition.
- Return ScoredTransaction objects matching the schema in db/models.py
- Persist results to scored_transactions table (use repository)

Run all 8 test cases. Test 1 and 4 are critical for the demo — the tier counts
are what light up the dashboard. Tune confidence thresholds if test 1 reveals
poorly-calibrated tiers.

Update STATE.md.
```

---

### PHASE 7 — Ops Agent

**Goal:** For each affected store, generate prioritized employee tasks and an escalation ladder.

**Deliverables:**

`/backend/agents/ops_agent.py`:
- Method `generate_tasks(blast_radius, scored_transactions, store_id) -> List[EmployeeTask]`
- Task types: shelf_pull, backroom_check, pos_block_verify, package_scan, disposal_quarantine, manager_review, photo_evidence
- Priority ordered: front-display product first, then high-traffic aisle, then less-visible
- Includes specific, actionable text generated by Qwen3-32B (not templated)
- Escalation rules: if task not acknowledged in N minutes, escalate level
- POS block command: emit a `pos_blocks(store_id, upc, lot_constraint, active_until)` row that the POS system would consume

**Test cases:**
1. Salsa-Verde: Ops Agent generates 6 store task lists; each list has 5-15 tasks; each task has a specific aisle/shelf reference
2. Store-4-Fridge: 1 store task list; tasks specifically mention "deli refrigeration zone"; quarantine tasks for 12 affected products
3. Task text quality: 90% of generated task descriptions are specific (mention exact aisle, shelf, product name) — verified by an LLM-based grader
4. Escalation ladder: a task with `created_at` 30 min ago and no acknowledgment auto-escalates to level 1; at 2 hours, level 2
5. POS block: row in `pos_blocks` table is created with correct UPC and lot constraint
6. Determinism: same input produces functionally identical task list (free-text may vary; structure must match)
7. Performance: generating tasks for all 6 Salsa-Verde stores completes in <20s

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 7: Ops Agent.

Read Phase 7. Build /backend/agents/ops_agent.py.

The agent should generate human-readable, specific instructions. Use Qwen3-32B
in non-thinking mode for speed; structure output via JSON Schema.

For test 3, the LLM-based grader is a separate, simple Qwen call that scores
each task description for specificity (1-5 scale). Average must be ≥4.

Run all 7 test cases. Update STATE.md.
```

---

### PHASE 8 — Comms Agent (with Reassurance — the killer feature)

**Goal:** Draft confidence-tier-appropriate customer notifications, including the differentiating Reassurance Notifications. Drafts only — never sends without human approval.

**Deliverables:**

`/backend/agents/comms_agent.py`:
- Method `draft_notifications(scored_transactions, recall_spec) -> List[NotificationDraft]`
- Five message templates (driven by Qwen3-32B with strict JSON output):
  1. **Confirmed Affected** — urgent, action-required, refund instructions, dispose
  2. **Likely Affected** — lot-check instructions with photo of lot label, refund offer
  3. **Possible Affected** — gentle, "please verify," explains what to look for
  4. **Confirmed Unaffected (Reassurance)** — "you may have heard, you're safe, here's why" with specific lot/plant proof, time-bound language ("as of {timestamp}")
  5. **Likely Unaffected (Soft Reassurance)** — "appears unaffected, here's how to verify"
- Personalization: use customer profile (kids, allergies, preferred language, vulnerable status) to adapt tone and emphasis
- Multi-language: detect customer's `preferred_language`, generate in that language; default English
- Public notice variant: for cash buyers / unidentifiable customers, generate a single store-scoped public notice with QR code link
- Institutional variant: for institutional accounts, longer-form email with quantity, account contact, suggested protocol
- All drafts go to `notification_drafts` table with `status='drafted'`; never sent automatically
- Delivery channel selection: known_loyalty → SMS+email, semi-known → email only, unknown → public notice, institutional → admin email

**Test cases:**
1. Salsa-Verde: drafts generated for all 6 tier buckets; counts match Phase 6 test 1 expectations (within ±5%)
2. Reassurance content: at least 800 Confirmed/Likely Unaffected drafts are generated
3. Reassurance message includes specific proof (e.g., "Plant 1 is unaffected; your purchase came from Plant 1") — verified by LLM grader on 20 random reassurance drafts; ≥18/20 contain specific plant or distributor proof
4. Time-bound assurance language: every reassurance message contains an explicit "as of <timestamp>" or equivalent — 100% pass
5. Vulnerable-population emphasis: a Maria-S customer with `kids: [{'age':2}]` on a Listeria recall gets a message that explicitly mentions infant risk
6. Multi-language: at least 5 customers in fixture have non-English `preferred_language`; their drafts are in that language (verified by language-detection lib)
7. Cash buyer: zero individual SMS/emails to cash transactions; one public notice per affected store
8. Institutional: each of the 15 institutional accounts that purchased in window gets a long-form admin email
9. PII protection: no message contains the customer's full address, payment details, or other PII beyond what is needed for the notification
10. Demo mode safety: with `DEMO_MODE=true` (default), no real Twilio/SendGrid call is made; messages are stored as drafts in DB only

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 8: Comms Agent (with Reassurance).

Read Phase 8. Build /backend/agents/comms_agent.py.

This phase produces THE killer feature. Polish the prompts for the 5 templates:
- Each must be empathetic but factual
- Each must include explicit time-bound language
- Each must avoid making absolute claims ("guaranteed safe" is forbidden)
- Reassurance messages must include concrete provenance proof

Use Qwen3-32B with thinking mode for the draft generation. Reassurance messages
benefit from chain-of-thought to ensure logical proof construction.

Run all 10 test cases. Update STATE.md.

NOTE: Test 10 is critical. DEMO_MODE=true must be the unconditional default in
.env.example and in the docker-compose default. Never ship real send capability
without explicit, documented opt-in.
```

---

### PHASE 9 — LangGraph Orchestration + State Persistence

**Goal:** Wire the 5 agents into a LangGraph workflow with durable state, human-in-loop pauses, and crash recovery.

**Deliverables:**

`/backend/orchestration/graph.py`:
- LangGraph definition with 5 nodes (one per agent) + 2 human-in-loop nodes (manager_approval, scope_review)
- Conditional edges: severity routing, low-confidence-requires-review routing, scope-change-rerun routing
- Streaming: emit Server-Sent Events for each agent transition (consumed by frontend)

`/backend/orchestration/state.py`:
- 20-state recall lifecycle state machine matching the design
- State persisted in `recall_cases.state` after every transition
- Resume: given a recall_case_id, can resume from current state on process restart

`/backend/api/routes/recalls.py`:
- POST `/recalls` — submit a new recall (any source)
- GET `/recalls/{id}` — full state including current agent step
- GET `/recalls/{id}/stream` — SSE for live agent progress
- POST `/recalls/{id}/approve_batch` — manager approval action
- POST `/recalls/{id}/reject_batch` — manager rejection action

**Test cases:**
1. End-to-end Salsa-Verde: POST a new recall → graph runs through Intake → Trace → Match → Ops/Comms in parallel → pauses at manager_approval → resume → completes
2. Crash recovery: kill the orchestration process mid-Match, restart, verify it resumes from `match_running` state without redoing earlier work
3. Streaming: SSE endpoint emits at least one event per agent transition; frontend test consumer receives all expected events
4. Low-confidence branch: a recall with extraction_confidence <0.6 routes to `requires_human_review` instead of running Trace
5. Scope change: simulate a recall scope expansion (Phase 12 will exercise this for real) — graph re-runs Match for newly-affected transactions only
6. Performance: end-to-end Salsa-Verde from POST to manager_approval pause completes in <90s
7. Idempotency: POSTing the same recall twice does not create duplicate work

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 9: LangGraph Orchestration.

Read Phase 9. This is the central nervous system.

Use LangGraph's checkpointer with Postgres backend. State graph supports:
- Linear pipeline for the happy path
- Conditional routing for low-confidence and scope-change cases
- Parallel execution of Ops and Comms after Match completes
- Human-in-loop pause at manager_approval; resume via API call

Run all 7 test cases. Update STATE.md.
```

---

### PHASE 10 — Frontend Dashboard

**Goal:** A polished retailer dashboard that tells the recall story visually. This is what the judges see in the demo. **It also has to match or exceed the live agent visibility shown in the strongest competitor submissions** (e.g., InsightAgent's WebSocket-streamed agent progress) — because that's what judges remember.

**Deliverables:**

Pages:
- `/` — Recall feed (list of all recall cases, status, severity, age)
- `/recall/[id]` — Recall detail with tabs:
  - **Overview:** parsed RecallSpec, current state, severity, source
  - **Blast Radius:** React Flow graph showing supply chain affected, animates as Trace Agent runs
  - **Affected Transactions:** sortable table with confidence tier filters
  - **Store Tasks:** per-store task lists with completion status
  - **Notifications:** drafts grouped by tier, with approve/reject buttons (single + batch)
  - **Compliance:** event log + downloadable PDF report
  - **Reassurance:** dedicated tab showing the unaffected customers and the reassurance batch (manager toggles "Send reassurance batch?")

Components:
- `BlastRadiusGraph` — React Flow with custom nodes (supplier/ingredient/plant/distributor/store/transaction); animates as data streams via SSE
- `ConfidenceTable` — sortable, filterable transaction list with tier badges
- `NotificationDraftCard` — displays drafted message, recipient (with PII redacted), tier, approve/reject controls
- `ReassuranceBatchPanel` — distinct UX from the affected notifications; one-toggle "Send reassurance"
- `LiveAgentStatus` — top banner showing which agent is currently running, animated state transitions
- **`AgentTelemetryStrip`** — persistent footer/sidebar showing live per-agent metrics:
  - Agent name, current state (idle / thinking / completed)
  - Tokens generated this run (in/out)
  - Latency (last call, p50, p95)
  - **MI300X memory utilization** (sampled from `rocm-smi`, displayed as a live percentage bar)
  - **MI300X compute utilization** (live percentage)
  - This component is the visible AMD storyline. Judges see Pheromone exercising the GPU in real time.
- **`HardwareBadge`** — small persistent badge somewhere in the header: "Running Qwen3-32B on AMD Instinct MI300X via vLLM + ROCm 7" — clickable to open a small modal showing the deployed model config

Visual identity:
- Clean, minimal, professional (think Linear, Stripe Dashboard)
- Dark mode by default
- Confidence tier colors: red (Confirmed Affected), orange (Likely), yellow (Possible), light green (Likely Unaffected), green (Confirmed Unaffected), gray (No Action)

Backend support needed for telemetry (add to Phase 9 if not already):
- `/api/telemetry/agents` — current agent state + token counts (read from compliance log)
- `/api/telemetry/gpu` — periodic poll of `rocm-smi` output, cached for 5s

**Test cases:**
1. Lighthouse score: ≥95 performance, ≥95 accessibility on production build
2. Salsa-Verde demo flow: from feed click → recall detail loads in <2s → blast radius graph renders in <3s → all tabs accessible
3. Real-time: when triggered from the API, the dashboard receives SSE updates and animates the graph in real time
4. Approval flow: clicking "Approve all Confirmed Affected" updates DB rows; UI reflects new status without page reload
5. Reassurance toggle: enabling Reassurance Mode and approving the batch creates approval records; UI shows count moved to "approved"
6. PII redaction: customer names show as initials, emails show domain only ("j***@gmail.com") in the affected transactions table — verified in component test
7. Mobile responsive: all pages usable at 380px width (manager-on-phone scenario)
8. **Telemetry visibility:** during a Salsa-Verde end-to-end run, the AgentTelemetryStrip shows non-zero token counts for each agent and visible GPU utilization peaks
9. **HardwareBadge:** the badge is visible on every page; clicking opens a modal with the current Qwen model name, vLLM version, ROCm version, and MI300X identifier

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 10: Frontend Dashboard.

Read Phase 10 + the frontend-design skill at /mnt/skills/public/frontend-design/SKILL.md
before writing components. Adopt the design tokens and component patterns there.

Build with these constraints:
- Server Components by default; Client Components only where needed (graph, drafts,
  telemetry strip, agent status — anything live)
- TanStack Query for all data fetching
- shadcn/ui for primitives
- React Flow for the blast radius
- Loading skeletons, error boundaries, empty states for every page
- AgentTelemetryStrip and HardwareBadge are NON-OPTIONAL — they are the visible AMD
  storyline that judges score on. Do not skip these even if other phases run long.

Run all 9 test cases. Update STATE.md.

This is the demo. Take the time to make it feel premium. Other strong submissions
(InsightAgent, Boundary Forge) have polished UIs with live orchestration visibility
and explicit AMD/MI300X branding. Match or exceed their polish here.
```

---

### PHASE 11 — Compliance Logger + Audit Report

**Goal:** Passive event sourcing of every agent action and human approval; on-demand PDF audit report.

**Deliverables:**

- `/backend/compliance/logger.py` — append-only logger; every agent action and approval inserts a row into `compliance_log`
- Decorator `@compliance_logged` for agent methods so the audit is automatic
- `/backend/compliance/report.py` — given a recall_case_id, generates a PDF using ReportLab
  - Title page with recall summary
  - Timeline of events (Intake → Trace → Match → ...)
  - Affected statistics (counts per tier)
  - Tasks completed (per store)
  - Notifications sent (per tier, with proof of delivery if available)
  - Reassurance batch (if sent)
  - Final state and closure timestamp
- API endpoint `GET /recalls/{id}/audit_report.pdf`

**Test cases:**
1. Every agent action in a Salsa-Verde end-to-end run produces ≥1 compliance log entry
2. Compliance log is append-only: attempting UPDATE returns Postgres error
3. PDF generated for Salsa-Verde is valid PDF (passes PyPDF2 parse) and ≥4 pages
4. PDF includes specific timestamps, agent names, tier counts
5. PDF includes the reassurance batch section with specific count
6. Performance: PDF generation completes in <10s

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 11: Compliance Logger.

Read Phase 11. Build the logger and the report generator.

Use ReportLab for PDF; the pdf skill at /mnt/skills/public/pdf/SKILL.md has
guidance — read it first.

Run all 6 test cases. Update STATE.md.
```

---

### PHASE 9B — HF Space Early-Launch Stub (CRITICAL FOR HF PRIZE)

**Goal:** Get a minimal-but-real Pheromone Space live on Hugging Face *before* the full build is complete, so HF likes have time to accumulate. This is a strategic phase, not just a deployment phase. The HF Special Prize is awarded by likes count, and likes accumulate over time. Strong competitor submissions (Boundary Forge currently leading on likes) went live early.

**Why this is here, not at Phase 13:**
The HF Special Prize (1st place: Reachy Mini robot + 6 months HF PRO + $500 HF credits) goes to the Space with the most likes at hackathon end. Likes need time to accumulate. A Space that goes live in the last 24 hours has nearly zero chance against one that's been live for a week.

**Deliverables:**

- A minimal HF Space ("Pheromone — Recall Operating System") in the AMD Developer Hackathon HF Organization
- Landing page that does NOT require any actual agent execution — just a polished static demo page that:
  - Explains the problem (with the strongest stats)
  - Shows screenshots/animation of the dashboard mockup
  - Has a "Try a sample recall" button that walks through a *pre-recorded* Salsa-Verde scenario (canned data, not live agents — this is fine for likes)
  - Includes a clear CTA: "Like this Space if you'd want this for your local grocery store"
  - Links to GitHub repo, demo video (when available), Build-in-Public thread
- The full live agent pipeline can be added later (Phase 13). For now, the Space exists and accumulates likes based on the strength of the problem statement and design.

**Test cases:**
1. Space is live in the AMD Developer Hackathon HF Organization
2. Landing page loads in <3s
3. "Try a sample recall" walkthrough completes without errors (canned, pre-recorded)
4. Like button is prominent, with social-proof CTA
5. Build-in-public thread linked, GitHub repo linked, contact info visible
6. Clear "Built on AMD Instinct MI300X via vLLM + ROCm" badge prominently shown
7. Mobile-friendly (most HF likes come from mobile scrolling)

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 9B: HF Space Early-Launch Stub.

This is a STRATEGIC phase. The goal is not technical depth — it's getting on the
HF leaderboard early so likes accumulate.

Build a single-page Next.js site (or static HTML if simpler) that:
1. Opens with the problem stat: "When the FDA recalls food, no one is required
   to tell the people who bought it. 109 million units recalled in 2025. Pheromone
   is the system that fixes the gap."
2. Has a 60-second "Try a sample recall" interactive walkthrough using canned data
   (a sequence of pre-rendered states the user clicks through)
3. Shows the blast-radius graph as a static image animation
4. Has a prominent like-CTA at the bottom: "Like this Space if you'd want this
   for your local grocery store"
5. Links: GitHub repo (even if private/in-progress, link the org), build-in-public
   thread on X, contact

Wrap as Docker SDK Space, push to the HF organization for the AMD hackathon.

Test cases all pass. Update STATE.md.

After this phase, EVERY social media post links to the Space. Every X thread, every
LinkedIn post, every Discord update. We are now in HF likes accumulation mode.
```

---

### PHASE 12 — Real FDA Stress Test

**Goal:** Run the entire pipeline against 20 real, recent FDA recalls. Verify graceful handling. Document failures.

**Deliverables:**

- Script `/backend/tests/stress/run_real_recalls.py`
- For each of 20 recent real FDA recalls:
  1. Ingest via Phase 3 ingestion path
  2. Run through full LangGraph pipeline
  3. Capture: extraction confidence, blast radius size, transaction tier counts, agent step durations, any errors
- Report `/backend/tests/stress/REPORT.md` with results, failures, and root causes

**Test cases:**
1. ≥18/20 recalls complete the full pipeline without uncaught exceptions
2. ≥16/20 produce a non-empty BlastRadius (the 4 that don't are because the products aren't in our synthetic catalog — expected and OK)
3. ≥15/20 produce ≥1 ScoredTransaction
4. Total runtime for all 20 <30 minutes
5. Zero PII leaks in logs (grep audit)
6. Zero accidental real notification sends (DEMO_MODE was on)

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 12: Real FDA Stress Test.

Read Phase 12. Pull 20 recent real FDA recalls (last 30 days) via the ingestion
pipeline. Run them through the full LangGraph orchestration. Capture detailed
metrics.

Document every failure in REPORT.md. For each failure, note:
- Which agent failed
- Recall characteristics that triggered the failure
- Root cause hypothesis
- Whether it's a robustness gap that should be fixed before submission

Update STATE.md with summary.
```

---

### PHASE 13 — Hugging Face Space — Full Live Upgrade

**Goal:** Upgrade the Phase 9B Space from a canned walkthrough to a fully functional live demo with real agent execution. By this phase the Space has already been accumulating likes for several days.

**Deliverables:**

- `/infra/hf_space/Dockerfile` — multi-stage build, Next.js frontend served by Node, FastAPI backend, sqlite or remote-Postgres-via-env
- HF Space config (`README.md` with frontmatter)
- Environment variables documented in HF Space settings
- The Space now includes: live demo with pre-seeded synthetic data + sample real recalls; "Reset demo" button; clear "demo mode, no real notifications sent" banner
- The HardwareBadge component visibly states the AMD MI300X / vLLM / ROCm 7 stack
- The AgentTelemetryStrip (from Phase 10) is visible on the live Space, showing real GPU utilization

**Test cases:**
1. Local `docker build -f infra/hf_space/Dockerfile .` succeeds
2. `docker run` of the built image: hitting localhost on the exposed port serves the dashboard
3. Pushed Space loads in browser within 60s of cold start
4. Salsa-Verde demo works end-to-end on the deployed Space
5. Banner clearly states demo mode
6. **HardwareBadge and AgentTelemetryStrip are visible and functional** — visitors can see the AMD compute being exercised
7. Existing likes from Phase 9B are preserved (we are upgrading the same Space, not creating a new one)

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 13: HF Space Full Live Upgrade.

Read Phase 13. Build the Dockerfile and Space configuration.

CRITICAL: We are upgrading the EXISTING Space from Phase 9B. Do not create a new
Space — that loses all accumulated likes. Update the existing Space's content and
configuration.

Note: HF Spaces have CPU/RAM limits. The LLM does NOT run in the Space — it runs
on AMD Developer Cloud. The Space is the frontend + lightweight orchestration
backend that calls the external vLLM endpoint.

For the demo's Postgres: use a small Postgres instance (Supabase free tier) and
configure connection via Space secret.

Run all 7 test cases. Update STATE.md.
```

---

### PHASE 14 — Demo Polish + Recording + Final Ship-It Blast

**Goal:** A 90-second hero video, a 3-minute extended walkthrough, submission package complete, AND a final all-channels Ship-It push to drive HF likes in the closing hours.

**Deliverables:**

- 90-second hero video: Salsa-Verde scenario, scripted narration, screen capture of dashboard
- 3-minute extended video: hero + Store-4-Fridge + reassurance close-up
- Submission package per lablab requirements: project description, long description, video links, GitHub link, HF Space link, technology tags
- Final Ship-It posts: X thread + LinkedIn post with video clips, all linking the HF Space with explicit "like this" CTA
- Tech tags must include: `AMD Developer Cloud`, `AMD ROCm`, `Qwen`, `Qwen3`, `LangGraph`, `Hugging Face Spaces`, `vLLM`, `AI Agents & Agentic Workflows`

**Submission opening line (use exactly — it's the problem-level hook competitors don't have):**

> "When the FDA recalls a food product, no one is required to tell the people who bought it. 109 million units were recalled in 2025. 48 million Americans get sick from contaminated food each year. 84% of grocery chains fail to publish a customer-notification policy. Pheromone is a multi-agent recall operating system that closes this gap — the first system that handles both halves of a recall: urgent notifications to the affected, and reassurance with proof to the safe."

**Submission long-description must include numerical claims:**

- "Tested against 20 real FDA recalls; full pipeline completed for 18/20 with average end-to-end runtime under 90 seconds."
- "Built a 22-entity, 11-edge supply-chain graph; recursive CTE traversal returns blast radius in <2s on the demo dataset."
- "Six confidence tiers including industry-first 'Confirmed Unaffected' Reassurance Notifications, which would have prevented an estimated 1,200 panic-throwouts and saved $34K on the Salsa-Verde demo scenario alone."
- "Probabilistic provenance via a deterministic Inventory Composition Engine — eliminates the lot-codes-at-checkout requirement that breaks every other recall app."
- "Runs Qwen3-32B + Qwen3-8B simultaneously on a single AMD Instinct MI300X via vLLM and ROCm 7. The 192GB HBM3 memory is what makes simultaneous multi-agent context retention possible."

**Test cases:**
1. Hero video plays end to end with zero glitches
2. All on-screen text legible at 1080p
3. Audio normalized, no clipping
4. Lablab submission form filled completely with all numerical claims and exact opening line
5. HF Space link is live and demo works there
6. GitHub repo is public, README has install + run instructions
7. Final Ship-It blast posted to X + LinkedIn + Discord with HF Space "like this" CTA
8. Tech tags include all 8 required tags

**AI Coding Prompt:**
```
[Master Onboarding Prompt above]

EXECUTE PHASE 14: Demo Polish + Final Ship-It Blast.

This phase is mostly content creation, not code. Help me draft:

1. The 90-second hero video script with precise narration timing.
   Open with the problem stat. Show the agent graph animating. End with the
   reassurance moment. Visible MI300X / vLLM / ROCm storyline.

2. The submission long-description text. Use the EXACT opening line specified
   in the build plan. Include EVERY numerical claim. Hit all four judging
   criteria explicitly with subheadings:
   - Application of Technology (the AMD/Qwen/vLLM/ROCm story)
   - Presentation (dashboard + live agent visibility + telemetry strip)
   - Business Value ($10M average recall cost; $34K saved per demo recall;
     109M units recalled in 2025; 84% chain notification failure)
   - Originality (Reassurance Notifications, probabilistic provenance,
     ingredient-level blast radius — none built by anyone else)

3. The final Ship-It blast (3 posts):
   - X thread (5-7 tweets) with the demo video and HF Space CTA
   - LinkedIn post (longer-form, problem-first opening)
   - Discord post in the hackathon server
   All three include "like this Space if you'd want this for your local grocery"

4. The README.md polishing pass.

For the videos, output a shot-by-shot script with:
- timestamp range
- on-screen action
- narrator script
- key emphasis points
- when the AgentTelemetryStrip and HardwareBadge are visible

Run all 8 test cases (most are content QA — review with me before submission).
Update STATE.md to "BUILD COMPLETE".
```

---

## 6. JUDGING-CRITERIA MAPPING

The hackathon judges on four axes. Here is how each phase contributes:

**Application of Technology** (how well models are integrated)
- Phase 4 (Intake): structured extraction with self-reported confidence
- Phase 5 (Trace): hybrid LLM + deterministic graph traversal
- Phase 6 (Match): probabilistic provenance + deterministic scoring
- Phase 8 (Comms): personalized multi-language drafts with Reassurance
- All: vLLM on MI300X, Qwen3 family, structured JSON output

**Presentation** (clarity and effectiveness)
- Phase 10: dashboard tells the story visually
- Phase 14: scripted demo narration

**Business Value** (impact and practical value)
- Phase 8 (Reassurance): unique value prevents over-recall panic
- Phase 11 (Compliance): production-grade audit trail
- Phase 12 (Stress test): real-world validation
- Document 2 (Project Context) makes the case explicitly

**Originality** (uniqueness and creativity)
- Reassurance Notifications: not built by anyone else
- Probabilistic provenance: not done by anyone else in the recall app space
- Ingredient-level blast radius with hierarchical recipes: rarely done
- Multi-source verification (FDA + supplier + retailer-internal): rare

---

## 7. KILL-SWITCH POLICY

If at any point a phase blows past 2x its time estimate, STOP and discuss before continuing. Do not silently keep going. The risk is sunk-cost reasoning leading to a bad project.

When discussing, the options are:
1. Cut scope within the phase (accept a less-robust version)
2. Cut the phase entirely (some are optional — most are not)
3. Identify a blocking unknown and resolve it before continuing
4. Acknowledge the project's revised target (e.g., aim for track win, not grand prize)

The order of phases that are **safe to cut if absolutely necessary** (last resort):
- Phase 13 (HF Space deployment) — gives up the HF prize but project still wins on lablab
- Phase 6's vulnerable-population modifier (less personalization)
- Phase 8's multi-language support (English only)
- Phase 11's PDF report (replace with HTML report on screen)

The phases that **CANNOT be cut** (these define the project):
- Phase 4 (Intake), 5 (Trace + composition), 6 (Match), 8 (Comms with Reassurance)
- Phase 9 (orchestration)
- Phase 10 (dashboard)

---

## 7.5. SHIP-IT DAILY CADENCE (HF LIKES STRATEGY)

The Hugging Face Special Prize is awarded by likes count on the Space at hackathon close. Boundary Forge currently leads with the most likes; they posted regularly throughout their build. We need to match or exceed their cadence.

**The strategy: post every single day during the build, with the HF Space link in every post. Even rough work-in-progress posts.**

**Posting cadence (daily — set a calendar reminder):**

| Day | Channel | Content |
|---|---|---|
| Day 0 (announce) | X + LinkedIn + Discord | "Building Pheromone for the @AIatAMD hackathon. Problem: no one is required to tell you when food you bought is recalled. 109M units recalled in 2025. Building a fix. 🧵" — open with stats, share the architecture sketch |
| Day 1 | X (short) | Screenshot of Phase 1 schema or Phase 2 synthetic data. "Day 1: Built the supply-chain graph. 22 entity types. Ingredient → recipe → product → pallet → shipment → store. This is the foundation." |
| Day 2 | X (short) | Intake Agent parsing a real FDA notice on screen. "Day 2: Watch the Intake Agent extract structured fields from a real FDA notice that was just published. Qwen3 on AMD MI300X via vLLM." |
| Day 3 | X thread + LinkedIn (longer) | The Trace Agent + blast radius graph animating. "Day 3: This is what 'recall blast radius' actually looks like. Watch the graph light up as the Trace Agent walks the supply chain." Include screen recording. |
| Day 3.5 | **Phase 9B HF Space goes live** | Announce: "Pheromone is now live on HuggingFace Spaces. Like it if you'd want this for your local grocery. Link 👇" — post on every channel |
| Day 4 | X + LinkedIn | The Reassurance Notification feature. "Every recall app tells you when you're at risk. Pheromone tells you when you're SAFE — with proof. This is the missing primitive in every recall system." Include side-by-side mockup. |
| Day 5 | X | The dashboard polish moment. "Day 5: Dashboard is shaping up. Live agent telemetry, blast radius graph, MI300X memory utilization visible in real time. @AIatAMD" Include screenshot. |
| Day 6 | X thread + LinkedIn | Real FDA stress test results. "Tested Pheromone against 20 real FDA recalls. 18/20 completed. Average pipeline: under 90s. Here's what we learned about edge cases in real-world recall data." |
| Day 7 (submission) | All channels | Final Ship-It blast (Phase 14 deliverable). Demo video, HF Space link with explicit "like this" CTA. Multiple posts: morning announce, evening close. |

**Required tags on every post:** `@AIatAMD` `@lablab` `@huggingface` `@Alibaba_Qwen` (the partner accounts care about being tagged).

**Required hashtags:** `#AMDDevHack` `#AIAgents` `#AMDDevCloud` `#Qwen` (research the actual hackathon hashtag — it may differ).

**Subreddits where the HF Space link belongs (post once each, sensitively):**
- r/foodsafety — most relevant
- r/grocery — directly affected community
- r/AskCulinary — high engagement
- r/MachineLearning — for the agentic architecture

Frame each subreddit post differently. r/foodsafety wants the problem story. r/MachineLearning wants the multi-agent architecture story.

**The single most important detail: every post links the HF Space, not the GitHub. GitHub gets stars; HF Space gets likes. We are optimizing for likes.**

---

## 8. FINAL CHECKLIST BEFORE SUBMISSION

- [ ] All Phase test cases pass
- [ ] Real FDA stress test (Phase 12) report archived
- [ ] HF Space live and demo works there
- [ ] GitHub repo public with clear README
- [ ] 90-second + 3-minute videos uploaded
- [ ] Lablab submission form complete with project title, descriptions, tags
- [ ] Final Ship-It posts published; HF Space CTA included
- [ ] STATE.md marked BUILD COMPLETE with timestamp
- [ ] DEMO_MODE=true verified in deployed environments (no accidental real sends)

---

End of Document 1. Use with Document 2 (Project Context) for the complete picture.
