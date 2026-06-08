from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import build_graph
from db import get_analyses_by_product, get_product, get_products, get_reviews_by_product, init_db, insert_review, save_analysis

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


class UserInput(BaseModel):
    product_id:  int
    review:      str
    rating:      float | None = None
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
    save_analysis(review_id, final)


@app.post("/api/analyze")
async def run_agent(body: UserInput, background_tasks: BackgroundTasks):
    review_id = insert_review(body.product_id, body.review, body.rating)
    background_tasks.add_task(_run_agent, review_id, body.review, body.max_retries)
    return {"id": review_id}


@app.get("/api/products")
def list_products():
    return get_products()


@app.get("/api/products/{product_id}")
def get_product_detail(product_id: int):
    product = get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.get("/api/reviews/{product_id}")
def get_reviews(product_id: int):
    return get_reviews_by_product(product_id)


@app.get("/api/analyses/{product_id}")
def get_analyses(product_id: int):
    return get_analyses_by_product(product_id)
