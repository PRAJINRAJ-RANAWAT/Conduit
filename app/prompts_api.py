"""Prompt versions (immutable) and the optimiser endpoint."""
from fastapi import APIRouter, Depends, HTTPException

from app import db, optimiser
from app.auth import get_tenant

router = APIRouter(dependencies=[Depends(get_tenant)])

LABELS = "Classify the sentiment of the review as positive or negative."
SEED = {  # the same task written 5 ways, from long to short
    1: f"{LABELS} Answer with one word.\nExample: 'Loved it' -> positive\nExample: 'Hated it' -> negative\n"
       "Example: 'Works great' -> positive\nExample: 'Fell apart' -> negative\nReview: {text}\nAnswer:",
    2: f"{LABELS} Answer with one word.\nExample: 'Loved it' -> positive\nExample: 'Hated it' -> negative\nReview: {{text}}\nAnswer:",
    3: f"{LABELS} Answer with one word.\nExample: 'Loved it' -> positive\nReview: {{text}}\nAnswer:",
    4: f"{LABELS} Answer with one word. Review: {{text}}",
    5: "Sentiment? {text}",
}


def seed(name: str = "sentiment"):
    for v, template in SEED.items():
        db.run("INSERT INTO prompt_versions (name, version, template) VALUES (%s,%s,%s) "
               "ON CONFLICT DO NOTHING", (name, v, template))


@router.get("/prompts/{name}/versions")
def versions(name: str):
    return db.run("SELECT version, template FROM prompt_versions WHERE name=%s ORDER BY version",
                  (name,))


@router.post("/prompts/{name}/versions", status_code=201)
def add_version(name: str, body: dict):
    """Versions can only be ADDED. There is no edit or delete (the DB refuses it as well)."""
    row = db.run("""INSERT INTO prompt_versions (name, version, template)
                    SELECT %s, COALESCE(MAX(version), 0) + 1, %s FROM prompt_versions
                    WHERE name=%s RETURNING version""", (name, body["template"], name))
    return row[0]


@router.post("/prompts/optimise")
def run_optimiser(body: dict):
    name, epsilon = body.get("name", "sentiment"), body.get("epsilon", 0.1)
    vs = db.run("SELECT version, template FROM prompt_versions WHERE name=%s ORDER BY version",
                (name,))
    if not vs:
        raise HTTPException(404, "unknown prompt")
    return optimiser.optimise(vs, epsilon)
