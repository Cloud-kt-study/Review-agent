import json

import pymysql
import pymysql.cursors

from env import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME


def get_db():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
    )


def init_db():
    con = get_db()
    try:
        cur = con.cursor()
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS aspects (
                id         INT PRIMARY KEY AUTO_INCREMENT,
                aspect     VARCHAR(100) NOT NULL UNIQUE,
                status     VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
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


def get_active_aspects() -> list[str]:
    con = get_db()
    try:
        cur = con.cursor()
        cur.execute("SELECT aspect FROM aspects WHERE status = 'active'")
        return [r[0] for r in cur.fetchall()]
    finally:
        con.close()


def insert_review(review: str) -> int:
    con = get_db()
    try:
        cur = con.cursor()
        cur.execute("INSERT INTO reviews (review) VALUES (%s)", (review,))
        con.commit()
        return cur.lastrowid
    except Exception as e:
        con.rollback()
        raise e
    finally:
        con.close()


def save_review(state: dict) -> int:
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


def update_review(row_id: int, state: dict):
    items         = (state.get("analyzer_result") or {}).get("items", [])
    critic_result = state.get("critic_result") or {}

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
            state.get("reason_code"),
            state.get("retry_count", 0),
            row_id,
        ))
        con.commit()
    except Exception as e:
        con.rollback()
        raise e
    finally:
        con.close()


def get_unanalyzed_reviews() -> list[dict]:
    con = get_db()
    try:
        cur = con.cursor(pymysql.cursors.DictCursor)
        cur.execute(
            "SELECT id, review FROM reviews WHERE agent_aspect IS NULL OR agent_aspect = ''"
        )
        return cur.fetchall()
    finally:
        con.close()


def get_all_reviews() -> list[dict]:
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
