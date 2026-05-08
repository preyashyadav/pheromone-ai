# Pheromone – Architecture Corrections Log

This file captures “current truth” decisions that emerged during Phases 4–7 and
may not be reflected in the original build plan text. It is intended to prevent
architecture drift in future phases and in future AI sessions.

Last updated: 2026-05-08

## Phase 4–7 Decisions (CURRENT TRUTH)

### 1) LLM mode infrastructure (reusable pattern)
- `PHEROMONE_LLM_MODE` env flag:
  - default: `mock`
  - set to `real` to hit a real vLLM endpoint (OpenAI-compatible `/v1/chat/completions`)
- Intake tests exercise the “LLM path” without sockets/GPU by injecting an `httpx.Client` using `httpx.MockTransport`.
  - `backend/agents/intake_agent.py:IntakeAgent.__init__(..., client=None)`
  - `backend/tests/test_phase4_intake_agent.py:_agent()` builds the mock transport in-process.
- Smart-mock vLLM server exists for deterministic schema-shaped outputs:
  - `backend/mock_vllm_server.py` returns RecallSpec-shaped JSON in `choices[0].message.content`
  - The JSON generator lives in `_build_recall_spec_like_json(...)` and mirrors Phase 4 heuristics.
- Explicit escape hatch:
  - `PHEROMONE_INTAKE_SKIP_LLM=1` forces Intake to skip `_try_llm_extract` (deterministic-only).
- This pattern should be reused for any LLM-using agent (Phase 8 Comms, Phase 7 polish paths, etc.):
  - production: real vLLM endpoint + JSON Schema mode
  - tests: `httpx.MockTransport` returning schema-shaped JSON (no network/sockets required)

### 2) Salsa-Verde seed evolution (why the seed looks “weird”)
- Random generation excludes the Salsa-Verde UPC from random `finished_product_lots` so the SKU’s lots are controlled by the seed.
  - This fixed Phase 5 `affected_stock_fraction_peak` not reaching 1.0 (random clean lots were mixing early).
- Seeded Salsa-Verde stocking is deterministic:
  - seeded pallets are explicitly stocked; any incidental bulk-created stocking events for seeded pallets are deleted before inserting seeded ones.
- Late-window transaction injection is now intentionally structured to populate tiers “naturally”:
  - (a) 600 mixed no-capture → `possible_affected`
  - (b) 300 low-residual no-capture → `likely_unaffected` (added to avoid permanently-empty tier)
  - (c) 300 clean lot-capture → `confirmed_unaffected`
  - (d) everything else earlier in the window (includes affected-lot capture for `confirmed_affected` and ordinary probabilistic scoring)
- Design intent: every confidence tier should have non-zero representation driven by seed structure (not threshold hacks).

### 3) Verified Salsa-Verde tier distribution (current state)
Measured end-to-end (Intake→Trace→Match→Ops) using the deterministic LLM mock path:
- `confirmed_affected`: 451
- `likely_affected`: 1,389
- `possible_affected`: 680
- `likely_unaffected`: 300
- `confirmed_unaffected`: 780
- `no_action`: 0
- `total`: 3,600
- Reassurance-eligible (`likely_unaffected` + `confirmed_unaffected`): 1,080

### 4) Composition engine correctness fix
- `apply_events_to_units()` is required to replay sales correctly from an hourly snapshot:
  - sales must deplete the existing mixture, not just newly-stocked units.
  - this was a correctness bug in the early implementation and is now the required behavior.
  - see `backend/engine/composition_engine.py:apply_events_to_units()`

### 5) MatchAgent performance fix (Postgres parameter explosion)
- Loading many transactions via ORM `.in_([...])` can exceed Postgres/driver parameter limits.
- MatchAgent transaction loading uses `ANY(CAST(:ids AS uuid[]))` to avoid huge parameter lists:
  - `backend/agents/match_agent.py:_load_transactions()`

### 6) Test infrastructure conventions
- Full test suite lives in: `backend/tests/` + `data_generator/tests/`
- Run from repo root:
  - `./.venv/bin/python -m pytest backend/tests/ data_generator/tests/ -v`
- Current verified state:
  - 50 passed, 1 skipped (live openFDA gated by `PHEROMONE_LIVE_API_TESTS=1`), 0 failed
- Convention going forward: every phase ends with a full-suite run, not just that phase’s tests, to catch regressions.

### 7) Demo mode safety (Phase 8+)
- `PHEROMONE_DEMO_MODE` (default true) must prevent any real Twilio/SendGrid calls.
- In demo mode, notification workflows store drafts only; never send.

### 8) Pending real-LLM validation
- LLM-using agents currently exercise their code path via deterministic smart-mock (`httpx.MockTransport` / `backend/mock_vllm_server.py`).
- Real Qwen3-on-MI300X validation is pending AMD Developer Cloud access.
- When access arrives:
  - set `PHEROMONE_LLM_MODE=real`
  - set `VLLM_BASE_URL=<MI300X vLLM endpoint>`
  - re-run Phase 4+ tests to validate real JSON Schema constrained outputs.

## Phase 5 Corrections (CRITICAL)

### 1. Composition Engine Integration
- InventoryCompositionEngine MUST be used to compute stock fractions
- No direct or inferred assumptions allowed
- All probabilities derive from pallet composition

### 2. No Hardcoded Probabilities
- affected_stock_fraction_peak MUST be computed
- Hardcoding (e.g. = 1.0) is strictly forbidden
- 1.0 is valid ONLY if it emerges from composition

### 3. Deterministic Trace Agent
- TraceAgent must function fully without LLM
- vllm_config is optional
- All core logic is DB + computation

### 4. Phase Dependency Contract
- Phase 6 MUST consume composition-derived outputs
- Phase 7+ MUST NOT override probability logic
- LLMs are allowed ONLY for:
  - parsing (Phase 4)
  - communication (Phase 8)

## Key Principle

"All risk is computed, never assumed."
