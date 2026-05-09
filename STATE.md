# Pheromone Build State

Last updated: 2026-05-09T15:41:13Z
Repo: (local)
Branch: (local)
Last commit: (pending)

## Phases completed
- [x] Phase 0: Repo + environment setup (completed: 2026-05-08T07:30:23Z)
- [x] Phase 1: Database schema (completed: 2026-05-08T08:00:10Z)
- [x] Phase 2: Synthetic data generator (completed: 2026-05-08T08:34:08Z)
- [x] Phase 3: Real FDA data ingestion (completed: 2026-05-08T08:50:39Z)
- [x] Phase 4: Intake Agent (completed: 2026-05-08T09:09:10Z)
- [x] Phase 5: Trace Agent + InventoryCompositionEngine (completed: 2026-05-08T14:44:23Z)
- [x] Phase 6: Match Agent (completed: 2026-05-08T15:31:50Z)
- [x] Phase 7: Ops Agent (completed: 2026-05-08T16:10:19Z)
- [x] Phase 8: Comms Agent (with Reassurance) (completed: 2026-05-08T19:56:57Z)
- [x] Phase 9: LangGraph orchestration + state persistence (completed: 2026-05-08T22:03:03Z)
- [ ] Phase 9B: HF Space early-launch stub
- [ ] Phase 10: Frontend dashboard
- [ ] Phase 11: Compliance logger + audit report
- [ ] Phase 12: Real-FDA stress test (20 recalls)
- [ ] Phase 13: HF Space full live upgrade
- [ ] Phase 14: Demo polish + recording + final Ship-It blast

## Outstanding decisions
- None

## Known issues / TODOs
- Phase 0: AMD Developer Cloud + vLLM endpoint verification pending (requires manual provisioning).
- Phase 0/4: Phase 4 real-Qwen3 validation completed (2026-05-09T15:41:13Z); keep `PHEROMONE_LLM_MODE=mock` for fast dev iteration.

## Test case results (latest run per phase)
- Phase 0:
  - ✅ #1 `cd backend && pytest --collect-only`
  - ✅ #2 `cd frontend && npm run build`
  - ✅ #3 `docker compose up -d postgres` + `psql -h localhost -U postgres -c 'SELECT 1;'` (via `libpq`)
  - ✅ #4 `curl $VLLM_BASE_URL/v1/chat/completions` (local mock server on `http://127.0.0.1:8001`)
  - ✅ #5 `curl https://api.fda.gov/food/enforcement.json?limit=1` (works with network enabled)
  - ✅ #6 `git log` shows commit; `STATE.md` exists (note: repo root is parent `~/Documents`)

## Notes for the next session
- Keep the pheromone metaphor consistent in user-facing copy and errors (“lay a trail”, “signal selectively”, “protect the colony”).
- Phase 1:
  - ✅ #1 alembic upgrade head
  - ✅ #2 alembic downgrade base
  - ✅ #3 fixture inserts one row per table
  - ✅ #4 `cte_blast_radius_from_ingredient_lot` returns 12/12 transactions
  - ✅ #5 `cte_inventory_composition_at_time` matches expected distribution
  - ✅ #6 RecallCase CRUD round-trip via repositories
  - ✅ #7 100 concurrent `notification_drafts` inserts (no deadlock)
- Phase 2:
  - ✅ #1 generator runs <60s, exits 0
  - ✅ #2 row counts in expected ranges
  - ✅ #3 rerun with same seed stable
  - ✅ #4 Salsa-Verde seed verification
  - ✅ #5 Store-4-Fridge seed verification
  - ✅ #6 customer preferred-store consistency
  - ✅ #7 hierarchical recipe (seasoning blend) verification
- Phase 3:
  - ✅ #1 live openFDA pull (gated by `PHEROMONE_LIVE_API_TESTS=1`)
  - ✅ #2 offline replay: 25 fixtures ingested as verified raw notices
  - ✅ #3 source verification routing (malicious -> unverified signal; fda.gov -> verified)
  - ✅ #4 supplier inbox: 5 notices ingested as raw notices
  - ✅ #5 internal trigger creates `recall_case` in `signal_detected` with `source_type='retailer_internal'`
  - ✅ #6 de-dup by `recall_number` idempotent
  - ✅ #7 malformed fixture robustness (5/25) ingests with defaults

- Phase 4:
  - ✅ #1 openFDA fixtures: critical-field confidence >0.8 on ≥18/25 (real Qwen3 calibration)
  - ✅ #2 malformed fixtures flagged `requires_human_review` and never crash
  - ✅ #3 supplier inbox: extracts product + lot + hazard + severity (with low-confidence routing when ambiguous)
  - ✅ #4 internal triggers normalize to RecallSpec without any web fetch
  - ✅ #5 hazard mapping ≥23/25 against `backend/tests/fixtures/real_recalls/INDEX.md`
  - ✅ #6 severity mapping ≥22/25 against `backend/tests/fixtures/real_recalls/INDEX.md`
  - ✅ #7 idempotency: structured fields stable across repeated runs
  - ✅ #8 no PII: structured output redacts emails/phones (audit text preserved in `raw_notice_text`)

## Phase 4 risks / demo notes
- Supplier “Quality Alert” / investigation emails (no explicit hazard) are intentionally routed to human review (hazard confidence ~0.55) to avoid overconfident classification.
- Retraction notices (no recall initiated) currently normalize to a RecallSpec with low/unknown severity; the Ops Agent should treat these as “cancel / no action” signals when state machine wiring is added.

 - Phase 5:
  - ✅ #1 Salsa-Verde: Trace Agent returns exactly 6 affected stores; peak affected stock fraction reaches 1.0 (composition-derived)
  - ✅ #2 Store-4-Fridge: Trace Agent returns only Store 4
  - ✅ #3 Composition engine math correct on hand-crafted fixture
  - ✅ #4 Snapshot caching: second query faster (cache hit heuristic)
  - ✅ #5 Empty-composition sales edge returns empty dict (no crash)
  - ✅ #6 Facility inference: lot-code plant prefix infers facility, raises confidence
  - ✅ #7 Hierarchical propagation: ingredient -> blend -> >=5 finished products tagged
  - ✅ #8 Probabilistic correctness: 60/40 pallets returns affected probability ~= 0.40 ± 0.02


IMPORTANT: Phase 5 completed with architecture corrections (see docs/ARCHITECTURE_NOTES.md)

- Phase 6:
  - ✅ #1 Salsa-Verde: tier counts hit thresholds (confirmed/likely/possible/reassurance buckets)
  - ✅ #2 Store-4-Fridge: window transactions scored as unaffected/no_action (no known affected pallets)
  - ✅ #3 Vulnerable-population modifier bumps tier for Listeria/Salmonella + dependents
  - ✅ #4 Reassurance eligibility: ≥800 unique customers in confirmed/likely-unaffected buckets
  - ✅ #5 Empty blast radius: returns [] (no crash)
  - ✅ #6 Cash degrade: confirmed -> likely when buyer unidentifiable
  - ✅ #7 Determinism: repeated runs identical tiers
  - ✅ #8 Performance: scores 2,000 transactions <30s

- Phase 7:
  - ✅ #1 Salsa-Verde: 6 store task lists; 5–15 tasks each; aisle/shelf references present
  - ✅ #2 Store-4-Fridge: tasks mention deli refrigeration zone; 12 quarantine tasks generated
  - ✅ #3 Task specificity: heuristic grader average ≥4 (LLM grader pending real Qwen)
  - ✅ #4 Escalation ladder: open tasks auto-escalate after 30m/2h
  - ✅ #5 POS block: `pos_blocks` row created (UPC + lot constraint)
  - ✅ #6 Determinism: identical structure on repeated runs
  - ✅ #7 Performance: 6 stores <20s

- Phase 8:
  - ✅ Fix: `backend/tests/test_phase8_comms_agent.py` missing `ConfidenceTier` import (was causing NameError in test #5).
  - ✅ Local full-suite run (Docker enabled): `60 passed, 1 skipped (openFDA live), 0 failed` (completed: 2026-05-08T19:56:57Z)
