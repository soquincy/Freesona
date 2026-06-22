# fastapi_server.py: FastAPI endpoints for health checks and webhooks.
import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI, Request

app = FastAPI()
logger = logging.getLogger("FreesonaBot")

_mvsep_jobs: dict[str, asyncio.Future] = {}


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}


def register_mvsep_job(job_hash: str, future: asyncio.Future) -> None:
    _mvsep_jobs[job_hash] = future


def unregister_mvsep_job(job_hash: str) -> None:
    _mvsep_jobs.pop(job_hash, None)


def _mvsep_hash(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    if isinstance(data, dict):
        return data.get("hash") or data.get("job_hash")
    return payload.get("hash") or payload.get("job_hash")


@app.api_route("/webhooks/mvsep", methods=["GET", "POST"])
async def mvsep_webhook(request: Request):
    if request.method == "GET":
        return {"status": "ok"}

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        logger.info("MVSEP webhook test request received without JSON.")
        return {"status": "ok"}

    if not isinstance(payload, dict):
        logger.info("MVSEP webhook received non-object JSON.")
        return {"status": "ok"}

    job_hash = _mvsep_hash(payload)

    if not job_hash:
        logger.info("MVSEP webhook received without a job hash.")
        return {"status": "ok"}

    future = _mvsep_jobs.get(job_hash)
    if future and not future.done():
        future.set_result(payload)
    else:
        logger.info(f"MVSEP webhook received for unknown job hash: {job_hash}")

    return {"status": "ok"}
