from __future__ import annotations

from fastapi import FastAPI

from backend.api.routes.recalls import router as recalls_router


app = FastAPI(title="Pheromone API", version="0.0.1")
app.include_router(recalls_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
