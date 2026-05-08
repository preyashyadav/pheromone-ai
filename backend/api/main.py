from __future__ import annotations

from fastapi import FastAPI


app = FastAPI(title="Pheromone API", version="0.0.1")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}

