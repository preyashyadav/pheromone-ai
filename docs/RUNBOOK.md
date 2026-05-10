# Pheromone — Local Dashboard Runbook (Phase 10)

This is the fastest path to run the Phase 10 dashboard locally against a stable Postgres.

## Quickstart

```bash
# 1. Start local Postgres
./scripts/start_local_postgres.sh

# 2. Seed the demo recall (Salsa-Verde, fully populated)
./.venv/bin/python scripts/seed_demo_recall.py --reset

# 3. Start backend
./.venv/bin/python -m uvicorn backend.api.main:app --reload --port 8001

# 4. Start frontend (new terminal)
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001 npm run dev

# 5. Open browser
open http://localhost:3000
```

## Notes
- If `DATABASE_URL` is not set, both the backend and `scripts/seed_demo_recall.py` default to:
  - `postgresql+psycopg://postgres:postgres@localhost:5432/pheromone`
- To stop the local Postgres container:
  - `./scripts/stop_local_postgres.sh`

