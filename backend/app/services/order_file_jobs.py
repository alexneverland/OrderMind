"""Bounded in-memory async queue for large OCR/PDF file-preview extraction."""

import asyncio
from threading import Lock
import time
import uuid
from typing import Any, Optional

from backend.app.services.order_file_service import (
    OrderFileError,
    extract_order_file,
    validate_order_file_upload,
)

MAX_RETAINED_JOBS = 100
JOB_TTL_SECONDS = 1800.0

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = Lock()


class FilePreviewQueueFullError(RuntimeError):
    pass


def _expire_finished_jobs_locked(now: float) -> None:
    expired = [
        job_id
        for job_id, job in _jobs.items()
        if job["status"] in {"completed", "failed"} and now - job["updated_at"] > JOB_TTL_SECONDS
    ]
    for job_id in expired:
        _jobs.pop(job_id, None)


def _evict_for_insert_locked(now: float) -> None:
    _expire_finished_jobs_locked(now)
    while len(_jobs) >= MAX_RETAINED_JOBS:
        oldest_finished = next(
            (job_id for job_id, job in _jobs.items() if job["status"] in {"completed", "failed"}),
            None,
        )
        if oldest_finished is None:
            raise FilePreviewQueueFullError("File extraction queue is full; retry shortly")
        _jobs.pop(oldest_finished, None)


async def _run_file_preview_job(job_id: str, filename: str, content: bytes) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "processing"
            _jobs[job_id]["updated_at"] = time.monotonic()

    try:
        text, method = await extract_order_file(filename, content)
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "completed"
                _jobs[job_id]["text"] = text
                _jobs[job_id]["method"] = method
                _jobs[job_id]["updated_at"] = time.monotonic()
    except OrderFileError as exc:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["error"] = str(exc)
                _jobs[job_id]["updated_at"] = time.monotonic()
    except Exception:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["error"] = "Could not read this order file; check that it is valid and unprotected"
                _jobs[job_id]["updated_at"] = time.monotonic()


def submit_file_preview_job(filename: str, content: bytes) -> dict[str, Any]:
    """Validate upload upfront, enqueue async extraction, and never retain raw binary."""
    validate_order_file_upload(filename, content)
    job_id = uuid.uuid4().hex
    now = time.monotonic()
    record = {
        "job_id": job_id,
        "status": "pending",
        "filename": filename or None,
        "text": None,
        "method": None,
        "error": None,
        "updated_at": now,
    }
    with _jobs_lock:
        _evict_for_insert_locked(now)
        _jobs[job_id] = record
        snapshot = _public_job_view(record)

    asyncio.create_task(_run_file_preview_job(job_id, filename, content))
    return snapshot


def get_file_preview_job(job_id: str) -> Optional[dict[str, Any]]:
    now = time.monotonic()
    with _jobs_lock:
        _expire_finished_jobs_locked(now)
        record = _jobs.get(job_id)
        if record is None:
            return None
        return _public_job_view(record)


def _public_job_view(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": record["job_id"],
        "status": record["status"],
        "filename": record["filename"],
        "text": record["text"],
        "method": record["method"],
        "error": record["error"],
    }
