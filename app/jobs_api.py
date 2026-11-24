"""POST /jobs, GET /jobs/{id}, GET /jobs. The API only SAVES the job and QUEUES it; a worker runs it."""
from fastapi import APIRouter, Depends, Header, HTTPException, Response

from app import db, mq
from app.auth import get_tenant

router = APIRouter()


@router.post("/jobs", status_code=202)
def create_job(body: dict, response: Response, tenant: dict = Depends(get_tenant),
               idempotency_key: str = Header(default="")):
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    # Same (tenant, key) twice -> DO NOTHING, so we get no new row and return the old job.
    rows = db.run(
        """INSERT INTO jobs (tenant, idem_key, prompt, fail_times) VALUES (%s,%s,%s,%s)
           ON CONFLICT (tenant, idem_key) DO NOTHING RETURNING id, status""",
        (tenant["name"], idempotency_key, body["prompt"], body.get("fail_times", 0)))
    if not rows:
        job = db.run("SELECT id, status FROM jobs WHERE tenant=%s AND idem_key=%s",
                     (tenant["name"], idempotency_key))[0]
        response.status_code = 200            # "already exists", not "newly accepted"
        if job["status"] != "QUEUED":
            return {"id": str(job["id"]), "status": job["status"]}
        # Still QUEUED: the first call may have died before publishing. Re-publish; the worker
        # ignores duplicates, so this is safe.
        rows = [job]
    job_id = str(rows[0]["id"])
    try:
        mq.publisher.publish(mq.EXCHANGE, "work", {"job_id": job_id})
    except Exception:
        # Job is saved but not queued. Client retries with the same key and we re-publish.
        raise HTTPException(503, "queue unavailable, retry with the same Idempotency-Key")
    return {"id": job_id, "status": "QUEUED"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, tenant: dict = Depends(get_tenant)):
    rows = db.run("""SELECT id::text, status, attempts, result, error, prompt, fail_times
                     FROM jobs WHERE id=%s AND tenant=%s""", (job_id, tenant["name"]))
    if not rows:
        raise HTTPException(404, "no such job")
    return rows[0]


@router.get("/jobs")
def list_jobs(status: str = "", tenant: dict = Depends(get_tenant)):
    """Newest 100 jobs of this tenant, optionally only one status (DEAD = the DLQ view)."""
    return db.run("""SELECT id::text, status, attempts, error, created_at FROM jobs
                     WHERE tenant=%s AND (%s = '' OR status=%s)
                     ORDER BY created_at DESC LIMIT 100""", (tenant["name"], status, status))
