from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes.recalls import router as recalls_router
from backend.api.routes.dashboard import router as dashboard_router
from backend.api.routes.telemetry import router as telemetry_router


app = FastAPI(title="Pheromone API", version="0.0.1")

_cors_env = os.getenv("PHEROMONE_CORS_ORIGINS", "").strip()
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] if _cors_env else [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recalls_router)
app.include_router(dashboard_router)
app.include_router(telemetry_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
