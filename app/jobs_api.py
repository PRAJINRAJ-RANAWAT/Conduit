"""POST /jobs, GET /jobs/{id}, GET /jobs. The API only SAVES the job and QUEUES it; a worker runs it."""
from fastapi import APIRouter, Depends, Header, HTTPException, Response

from app import db
from app.auth import get_tenant

router = APIRouter()


@router.post("/jobs", status_code=202)
def create_job(body: dict, response: Response, tenant: dict = Depends(get_tenant),
               idempotency_key: str = Header(default="")):
    """Save the job (QUEUED) and return. The dispatcher publishes it to RabbitMQ when it is this tenant's turn,
    so even with RabbitMQ down the job is accepted and simply waits in Postgres."""
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    # Same (tenant, key) twice -> DO NOTHING, so we get no new row and return the old job.
    rows = db.run(
        """INSERT INTO jobs (tenant, idem_key, prompt, fail_times, work_secs, priority)
           VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (tenant, idem_key) DO NOTHING RETURNING id, status""",
        (tenant["name"], idempotency_key, body["prompt"], body.get("fail_times", 0),
         body.get("work_secs", 0), 1 if body.get("priority") == "interactive" else 0))
    if not rows:
        rows = db.run("SELECT id, status FROM jobs WHERE tenant=%s AND idem_key=%s",
                      (tenant["name"], idempotency_key))
        response.status_code = 200                # "already exists", not "newly accepted"
    return {"id": str(rows[0]["id"]), "status": rows[0]["status"]}


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
