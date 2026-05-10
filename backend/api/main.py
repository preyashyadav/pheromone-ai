from __future__ import annotations

from fastapi import FastAPI

from backend.api.routes.recalls import router as recalls_router
from backend.api.routes.dashboard import router as dashboard_router
from backend.api.routes.telemetry import router as telemetry_router


app = FastAPI(title="Pheromone API", version="0.0.1")
app.include_router(recalls_router)
app.include_router(dashboard_router)
app.include_router(telemetry_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
