# Pheromone — Technical Walkthrough (Build Notes)

This document is intended to satisfy the prompt:
> “Provide the link to your open-sourced project or the published technical walkthrough explaining how you built it.”

## Links (submission-ready)

- Open-source repo: `https://github.com/preyashyadav/pheromone-ai`
- Hugging Face Space (static walkthrough UI): `https://huggingface.co/spaces/lablab-ai-amd-developer-hackathon/pheromone`

## What Pheromone is

Pheromone is a recall operating system for food retail and supply-chain teams:

- Ingest recall notices into a structured `RecallSpec` contract
- Trace affected products through a supply-chain graph (lots, shipments, recipes/transformations)
- Match likely impacted purchases and compute confidence tiers
- Generate customer-safe notification drafts and store operations tasks
- Reassure customers who are not affected using provenance evidence
- Produce audit-ready compliance logs (append-only timeline + approvals)

## System overview

**Backend:** FastAPI + Postgres + deterministic tracing/computation where possible.  
**Frontend:** Next.js dashboard for the live demo UI.  
**HF Space:** a separate static HTML/CSS/JS walkthrough (served via Docker/Nginx).

Repo layout:

- `backend/`: FastAPI app, agents, orchestration, repositories, engine
- `frontend/`: Next.js dashboard UI
- `data_generator/`: synthetic supply-chain + POS data generator
- `hf-space-pheromone/`: static Space UI
- `docs/`: context, architecture notes, runbook, screenshots

## Recall workflow (end-to-end)

1. **Intake**: parse a recall notice into typed `RecallSpec`
2. **Trace**: traverse supply-chain graph to determine exposure paths + affected lots
3. **Match**: join trace evidence to transactions; compute confidence tiers
4. **Ops**: generate store tasks (pulls/quarantine/POS blocks) and priorities
5. **Comms**: draft tiered notifications + reassurance for safe customers
6. **Compliance**: persist a timeline of agent runs, approvals, and key transitions

## The five agents (contracted responsibilities)

- **Intake Agent**: notice text → `RecallSpec` JSON + extraction trace
- **Trace Agent**: `RecallSpec` + entities → exposure subgraph + affected lots
- **Match Agent**: exposure evidence + transactions → impacted set + confidence tiers
- **Ops Agent**: impact set + store context → task lists + priority
- **Comms Agent**: risk tier + provenance → customer-safe drafts + reassurance

## Reassurance (why it matters)

Most systems only notify affected customers. Pheromone also reassures customers who are *not* affected, using provenance evidence derived from the supply-chain trace. The goal is reducing panic, unnecessary refunds, and support load while preserving trust.

## AMD / GPU-backed inference (demo architecture)

The demo architecture runs a multi-agent stack with large-model inference enabled by:

- **Model:** Qwen3-32B
- **Serving:** vLLM
- **Driver stack:** ROCm 7
- **GPU:** AMD Instinct MI300X
- **Memory:** 192GB HBM3

The GPU doesn’t “solve recalls” — it enables realistic end-to-end inference and context retention for the demo stack.

## Local demo runbook

See `docs/RUNBOOK.md`.

Quickstart from repo root:

```bash
./scripts/start_local_postgres.sh
./.venv/bin/python scripts/seed_demo_recall.py --reset
./.venv/bin/python -m uvicorn backend.api.main:app --reload --port 8001

cd frontend
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001 npm run dev
```

Open `http://localhost:3000/recalls`.

### CORS (local dev)

For local dashboard dev (`http://localhost:3000` → `http://127.0.0.1:8001`), the backend enables CORS.
Override with:

```bash
PHEROMONE_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

## Tests

Run from repo root:

```bash
./.venv/bin/python -m pytest backend/tests/ data_generator/tests/ -v
```

## Screenshots

- `docs/overview.png`
- `docs/blast-radius.png`
- `docs/possible affected.png`
- `docs/multilingual-notificaton.png`

