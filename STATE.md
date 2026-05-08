# Pheromone Build State

Last updated: 2026-05-08T08:34:08Z
Repo: (local)
Branch: (local)
Last commit: (pending)

## Phases completed
- [x] Phase 0: Repo + environment setup (completed: 2026-05-08T07:30:23Z)
- [x] Phase 1: Database schema (completed: 2026-05-08T08:00:10Z)
- [x] Phase 2: Synthetic data generator (completed: 2026-05-08T08:34:08Z)
- [ ] Phase 3: Real FDA data ingestion
- [ ] Phase 4: Intake Agent
- [ ] Phase 5: Trace Agent + InventoryCompositionEngine
- [ ] Phase 6: Match Agent
- [ ] Phase 7: Ops Agent
- [ ] Phase 8: Comms Agent (with Reassurance)
- [ ] Phase 9: LangGraph orchestration + state persistence
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
- Phase 0: Temporary local mock vLLM server in use for test #4 (`backend/mock_vllm_server.py`).

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
