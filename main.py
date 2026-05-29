import os
from typing import TypedDict
 
import pymysql
from fastapi import FastAPI
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
 
# --- FastAPI ---
app = FastAPI()
 
# --- LLM ---
llm = ChatOpenAI(
    model="gpt-5-nano",
    temperature=0,
    api_key=os.environ.get("OPENAI_API_KEY")
)
 
# --- DB 연결 ---
def get_db():
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3308")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "agentdb"),
        charset="utf8mb4"
    )
 
# --- DB 초기화 ---
def init_db():
    con = get_db()
    try:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_log (
                id         INT PRIMARY KEY AUTO_INCREMENT,
                hym_msg    TEXT,
                ai_msg     TEXT,
                sys_msg    TEXT,
                result     TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        con.commit()
    except Exception as e:
        con.rollback()
        raise e
    finally:
        con.close()

init_db()

# --- State ---
class AgentState(TypedDict):
    hym_msg: str
    ai_msg:  str
    sys_msg: str
    result:  str
 
# --- LLM 노드 ---
def llm_node(state: AgentState) -> AgentState:
    SYSTEM_PROMPT = "너는 간단하게 대답만 하는 agent야."
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=state["hym_msg"]),
    ]
    response = llm.invoke(messages)
    return {
        **state,
        "ai_msg":  response.content,
        "sys_msg": SYSTEM_PROMPT,
        "result":  str(response.response_metadata),
    }
 
# --- 그래프 빌드 ---
def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("llm", llm_node)
    graph.set_entry_point("llm")
    graph.add_edge("llm", END)
    return graph.compile()
 
# --- DB 저장 ---
def save_to_db(state: AgentState):
    con = get_db()
    try:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO agent_log (hym_msg, ai_msg, sys_msg, result)
            VALUES (%s, %s, %s, %s)
        """, (state["hym_msg"], state["ai_msg"], state["sys_msg"], state["result"]))
        con.commit()
    except Exception as e:
        con.rollback()  # 트랜잭션 명시적 롤백
        raise e
    finally:
        con.close()     # 에러 나도 반드시 닫힘
 
# --- API 엔드포인트 ---
class UserInput(BaseModel):
    hym_msg: str
 
@app.post("/agent")
def run_agent(body: UserInput):
    graph = build_graph()
    final_state = graph.invoke({
        "hym_msg": body.hym_msg,
        "ai_msg":  "",
        "sys_msg": "",
        "result":  ""
    })
    save_to_db(final_state)
    return {
        "ai_msg": final_state["ai_msg"],
        "result": final_state["result"]
    }
 
@app.get("/")
def root():
    return {"status": "ok"}