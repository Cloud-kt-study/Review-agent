import ast
from dotenv import load_dotenv
load_dotenv()
import json
import os
from typing import Any, Dict, Literal, Optional, TypedDict

import pymysql
import pymysql.cursors
from fastapi import FastAPI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

# --- FastAPI ---
app = FastAPI()

# --- LLM ---
llm = ChatOpenAI(
    model="gpt-5-nano",
    temperature=0.2,
    api_key=os.environ.get("OPENAI_API_KEY"),
)

# --- DB 연결 ---
def get_db():
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3308")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "reviewdb"),
        charset="utf8mb4",
    )

# --- DB 초기화 ---
def init_db():
    con = get_db()
    try:
        cur = con.cursor()
        # 리뷰 분석 결과 테이블
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id             INT PRIMARY KEY AUTO_INCREMENT,
                review         TEXT,
                agent_aspect   TEXT,
                agent_label    TEXT,
                agent_evidence TEXT,
                verdict        VARCHAR(20),
                reason_code    VARCHAR(50),
                retry_count    INT DEFAULT 0,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        # 허용 속성 테이블
        cur.execute("""
            CREATE TABLE IF NOT EXISTS aspects (
                id         INT PRIMARY KEY AUTO_INCREMENT,
                aspect     VARCHAR(100) NOT NULL UNIQUE,
                status     VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        # 기본 속성 4개 삽입
        for a in ["보습", "가격", "향", "포장"]:
            cur.execute(
                "INSERT IGNORE INTO aspects (aspect, status) VALUES (%s, 'active')", (a,)
            )
        con.commit()
    except Exception as e:
        con.rollback()
        raise e
    finally:
        con.close()

init_db()

# ───────────────────────────────────────────────
# Agent State
# ───────────────────────────────────────────────
class ReviewState(TypedDict):
    review:           str
    analyzer_result:  Optional[Dict[str, Any]]
    critic_result:    Optional[Dict[str, Any]]
    reason_code:      Optional[str]
    repair_directive: Optional[str]
    retry_count:      int
    max_retries:      int
    next_agent:       Literal["analyzer", "critic", "end"]

# ───────────────────────────────────────────────
# 유틸
# ───────────────────────────────────────────────
REPAIR_TEMPLATES = {
    "OUTPUT_ERROR":   "dict 1개만 출력. 코드블록/설명 없이 items 구조와 label(0/1)을 맞춰라.",
    "SCOPE_ERROR":    "aspect는 허용된 속성만 사용하라. 다른 표현은 가장 가까운 허용 값으로 매핑하라.",
    "EVIDENCE_ERROR": "evidence는 리뷰 원문에 실제로 있는 연속된 문구만 사용하라.",
    "QUALITY_ERROR":  "리뷰에 없는 내용을 만들지 말고, 애매하면 해당 aspect는 제외하라.",
}

def _parse_dict(text: str, default: Any) -> Any:
    try:
        return ast.literal_eval(text)
    except Exception:
        return default

def get_active_aspects() -> list[str]:
    con = get_db()
    try:
        cur = con.cursor()
        cur.execute("SELECT aspect FROM aspects WHERE status = 'active'")
        return [r[0] for r in cur.fetchall()]
    finally:
        con.close()

# ───────────────────────────────────────────────
# LangGraph 노드
# ───────────────────────────────────────────────
def supervisor_node(state: ReviewState) -> ReviewState:
    if state.get("analyzer_result") is None:
        return {**state, "next_agent": "analyzer"}

    if state.get("critic_result") is None:
        return {**state, "next_agent": "critic"}

    verdict     = (state.get("critic_result") or {}).get("verdict")
    reason_code = state.get("reason_code")

    if verdict == "적합":
        return {**state, "next_agent": "end"}

    retry = state.get("retry_count", 0)
    if retry >= state.get("max_retries", 2):
        return {**state, "next_agent": "end"}

    return {
        **state,
        "retry_count":      retry + 1,
        "analyzer_result":  None,
        "critic_result":    None,
        "reason_code":      None,
        "repair_directive": REPAIR_TEMPLATES.get(
            reason_code,
            f"이전 분석이 부적합합니다(reason_code={reason_code}). 다시 분석하세요.",
        ),
        "next_agent": "analyzer",
    }


def analyzer_node(state: ReviewState) -> ReviewState:
    review           = state["review"]
    repair_directive = state.get("repair_directive") or ""
    aspect_str       = ", ".join(get_active_aspects())

    sys_msg = f"""# 역할 : 너는 상품 리뷰 분석 Agent.
# 목표 : 리뷰에서 언급된 속성만 추출하여 감성(긍정=1, 부정=0)을 판정.
# 속성 목록(이것만 허용): {aspect_str}
# 규칙:
- 속성은 언급된 것만 포함. 없으면 items는 빈 리스트.
- label은 0 또는 1만 사용.
- 같은 속성은 한 번만 출력.
- evidence는 리뷰 원문의 대표 근거 1개.
- 출력은 오직 Dictionary 1개. 코드블록/설명 없음.
# 출력 예시:
{{"items": [{{"aspect": "가격", "label": 0, "evidence": "가격이 조금 비싸요"}}]}}"""

    human_msg = f"리뷰: {review}\n수정 지시: {repair_directive}"

    response = llm.invoke([SystemMessage(content=sys_msg), HumanMessage(content=human_msg)])
    parsed   = _parse_dict(response.content, {"items": []})
    return {**state, "analyzer_result": parsed}


def critic_node(state: ReviewState) -> ReviewState:
    prompt = f"""너는 상품 리뷰 분석 결과를 검수하는 Critic Agent다.

[원본 리뷰]
{state["review"]}

[Analyzer 분석 결과]
{state.get("analyzer_result")}

판단 기준: 허용 속성만 사용했는지, label이 감성과 일치하는지, evidence가 원문에 존재하는지 확인.

[reason_code 목록]
OK / OUTPUT_ERROR / SCOPE_ERROR / EVIDENCE_ERROR / QUALITY_ERROR

[출력 형식] dict 1개만:
{{"verdict": "적합" 또는 "부적합", "reason_code": "...", "reason": "..."}}"""

    response = llm.invoke(prompt)
    result   = _parse_dict(
        response.content,
        {"verdict": "부적합", "reason_code": "OUTPUT_ERROR", "reason": "파싱 에러"},
    )
    return {
        **state,
        "critic_result": result,
        "reason_code":   result.get("reason_code", "QUALITY_ERROR"),
    }


def route_next(state: ReviewState) -> str:
    return state["next_agent"]


# ───────────────────────────────────────────────
# 그래프 빌드
# ───────────────────────────────────────────────
def build_graph():
    g = StateGraph(ReviewState)
    g.add_node("supervisor", supervisor_node)
    g.add_node("analyzer",   analyzer_node)
    g.add_node("critic",     critic_node)
    g.set_entry_point("supervisor")
    g.add_edge("analyzer", "supervisor")
    g.add_edge("critic",   "supervisor")
    g.add_conditional_edges(
        "supervisor",
        route_next,
        {"analyzer": "analyzer", "critic": "critic", "end": END},
    )
    return g.compile()

# ───────────────────────────────────────────────
# DB 저장
# ───────────────────────────────────────────────
def save_review(state: ReviewState) -> int:
    items         = (state.get("analyzer_result") or {}).get("items", [])
    critic_result = state.get("critic_result") or {}

    con = get_db()
    try:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO reviews
                (review, agent_aspect, agent_label, agent_evidence,
                 verdict, reason_code, retry_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            state["review"],
            json.dumps([i.get("aspect",   "") for i in items], ensure_ascii=False),
            json.dumps([i.get("label",    0)  for i in items], ensure_ascii=False),
            json.dumps([i.get("evidence", "") for i in items], ensure_ascii=False),
            critic_result.get("verdict"),
            state.get("reason_code"),
            state.get("retry_count", 0),
        ))
        con.commit()
        return cur.lastrowid
    except Exception as e:
        con.rollback()
        raise e
    finally:
        con.close()

# ───────────────────────────────────────────────
# API 엔드포인트
# ───────────────────────────────────────────────
class UserInput(BaseModel):
    review:      str
    max_retries: int = 2


@app.post("/api/analyze")
def run_agent(body: UserInput):
    graph = build_graph()
    final = graph.invoke({
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
def run_batch():
    """agent_aspect 가 NULL인 리뷰를 일괄 분석"""
    con = get_db()
    try:
        cur = con.cursor(pymysql.cursors.DictCursor)
        cur.execute(
            "SELECT id, review FROM reviews WHERE agent_aspect IS NULL OR agent_aspect = ''"
        )
        rows = cur.fetchall()
    finally:
        con.close()

    if not rows:
        return {"total": 0, "succeeded": 0, "failed": 0}

    graph     = build_graph()
    succeeded = 0
    failed    = 0

    for row in rows:
        try:
            final = graph.invoke({
                "review":           row["review"],
                "analyzer_result":  None,
                "critic_result":    None,
                "reason_code":      None,
                "repair_directive": None,
                "retry_count":      0,
                "max_retries":      2,
                "next_agent":       "analyzer",
            })
            items         = (final.get("analyzer_result") or {}).get("items", [])
            critic_result = final.get("critic_result") or {}

            con = get_db()
            try:
                cur = con.cursor()
                cur.execute("""
                    UPDATE reviews
                       SET agent_aspect   = %s,
                           agent_label    = %s,
                           agent_evidence = %s,
                           verdict        = %s,
                           reason_code    = %s,
                           retry_count    = %s,
                           updated_at     = CURRENT_TIMESTAMP
                     WHERE id = %s
                """, (
                    json.dumps([i.get("aspect",   "") for i in items], ensure_ascii=False),
                    json.dumps([i.get("label",    0)  for i in items], ensure_ascii=False),
                    json.dumps([i.get("evidence", "") for i in items], ensure_ascii=False),
                    critic_result.get("verdict"),
                    final.get("reason_code"),
                    final.get("retry_count", 0),
                    row["id"],
                ))
                con.commit()
            except Exception as e:
                con.rollback()
                raise e
            finally:
                con.close()

            succeeded += 1
        except Exception:
            failed += 1

    return {"total": len(rows), "succeeded": succeeded, "failed": failed}


@app.get("/api/reviews")
def get_reviews():
    con = get_db()
    try:
        cur = con.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT id, review, agent_aspect, agent_label, agent_evidence,
                   verdict, reason_code, retry_count, updated_at
              FROM reviews
             ORDER BY updated_at DESC
        """)
        return cur.fetchall()
    finally:
        con.close()