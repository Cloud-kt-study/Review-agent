from fastapi import FastAPI
from pydantic import BaseModel

from agent import build_graph
from db import get_all_reviews, get_unanalyzed_reviews, init_db, save_review, update_review

app = FastAPI()

init_db()


class UserInput(BaseModel):
    review:      str
    max_retries: int = 2


@app.post("/api/analyze")
async def run_agent(body: UserInput):
    graph = build_graph()
    final = await graph.ainvoke({
        "review":           body.review,
        "analyzer_result":  None,
        "critic_result":    None,
        "reason_code":      None,
        "repair_directive": None,
        "retry_count":      0,
        "max_retries":      body.max_retries,
        "next_agent":       "analyzer",
    })
    saved_id = save_review(final)
    items    = (final.get("analyzer_result") or {}).get("items", [])
    return {
        "id":          saved_id,
        "items":       items,
        "verdict":     (final.get("critic_result") or {}).get("verdict"),
        "reason_code": final.get("reason_code"),
        "retry_count": final.get("retry_count", 0),
    }


@app.post("/api/batch")
async def run_batch():
    rows = get_unanalyzed_reviews()
    if not rows:
        return {"total": 0, "succeeded": 0, "failed": 0}

    graph     = build_graph()
    succeeded = 0
    failed    = 0

    for row in rows:
        try:
            final = await graph.ainvoke({
                "review":           row["review"],
                "analyzer_result":  None,
                "critic_result":    None,
                "reason_code":      None,
                "repair_directive": None,
                "retry_count":      0,
                "max_retries":      2,
                "next_agent":       "analyzer",
            })
            update_review(row["id"], final)
            succeeded += 1
        except Exception:
            failed += 1

    return {"total": len(rows), "succeeded": succeeded, "failed": failed}


@app.get("/api/reviews")
def get_reviews():
    return get_all_reviews()
