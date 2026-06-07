from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel

from agent import build_graph
from db import get_all_reviews, init_db, insert_review, update_review

app = FastAPI()

init_db()


class UserInput(BaseModel):
    review:      str
    max_retries: int = 2


async def _run_agent(review_id: int, review: str, max_retries: int):
    graph = build_graph()
    final = await graph.ainvoke({
        "review":           review,
        "analyzer_result":  None,
        "critic_result":    None,
        "reason_code":      None,
        "repair_directive": None,
        "retry_count":      0,
        "max_retries":      max_retries,
        "next_agent":       "analyzer",
    })
    update_review(review_id, final)


@app.post("/api/analyze")
async def run_agent(body: UserInput, background_tasks: BackgroundTasks):
    review_id = insert_review(body.review)
    background_tasks.add_task(_run_agent, review_id, body.review, body.max_retries)
    return {"id": review_id}


@app.get("/api/reviews")
def get_reviews():
    return get_all_reviews()
