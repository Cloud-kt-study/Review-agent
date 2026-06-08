import json

import pymysql
import pymysql.cursors

from env import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

SAMPLE_PRODUCTS = [
    (1, "올리브영 비타민C 세럼 50ml", 18900, "산뜻하게 흡수되는 데일리 비타민C 세럼입니다.", "특가"),
    (2, "영국산 밤 1kg", 12500, "고소하고 달콤한 맛이 좋은 영국산 밤입니다.", None),
    (3, "NVDIA 주식 10주", 230000, "미래 성장 가능성을 기대해볼 수 있는 상품입니다.", "NEW"),
    (4, "삼성전자 이재용 회장님과의 식사 1회권", 1000000, "특별한 경험을 원하는 분들을 위한 프리미엄 상품입니다.", None),
    (5, "VITAHALO LED 아이클리너", 34900, "눈 주변을 편안하게 관리할 수 있는 LED 아이클리너입니다.", "특가"),
    (6, "자연산 물티슈 100매 1팩", 9900, "일상에서 부담 없이 사용하기 좋은 촉촉한 물티슈입니다.", None),
    (7, "아르마딜로 파스타", 4500, "간편하게 즐길 수 있는 독특한 풍미의 파스타입니다.", None),
    (8, "어린이 일회용 장갑 100매", 7800, "아이들이 위생적으로 사용할 수 있는 일회용 장갑입니다.", "NEW"),
    (9, "케로로 건담 1:1 사이즈", 5710000, "수집가를 위한 대형 사이즈 한정판 피규어 상품입니다.", "NEW"),
    (10, "두바이 콜드브루", 38800, "진하고 깔끔한 맛을 가진 프리미엄 콜드브루입니다.", "특가"),
    (11, "쫀득이 슬라임", 3000, "말랑하고 쫀득한 촉감으로 즐기는 슬라임입니다.", None),
    (12, "아삭아삭 얼음", 100, "시원하고 아삭한 느낌을 주는 재미있는 상품입니다.", "특가"),
]


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
            CREATE TABLE IF NOT EXISTS products (
                id          INT PRIMARY KEY,
                name        VARCHAR(255) NOT NULL,
                price       INT NOT NULL,
                description TEXT,
                badge       VARCHAR(50)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id             INT PRIMARY KEY AUTO_INCREMENT,
                product_id     INT,
                review         TEXT,
                rating         FLOAT,
                agent_aspect   TEXT,
                agent_label    TEXT,
                agent_evidence TEXT,
                verdict        VARCHAR(20),
                reason_code    VARCHAR(50),
                retry_count    INT DEFAULT 0,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_reviews_product
                    FOREIGN KEY (product_id) REFERENCES products(id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        cur.executemany("""
            INSERT INTO products (id, name, price, description, badge)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                price = VALUES(price),
                description = VALUES(description),
                badge = VALUES(badge)
        """, SAMPLE_PRODUCTS)
        cur.execute("""
            SELECT DATA_TYPE
              FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA = %s
               AND TABLE_NAME = 'reviews'
               AND COLUMN_NAME = 'product_id'
        """, (DB_NAME,))
        product_id_type = cur.fetchone()
        if product_id_type and product_id_type[0] != "int":
            cur.execute("""
                UPDATE reviews
                   SET product_id = NULL
                 WHERE product_id IS NOT NULL
                   AND product_id NOT REGEXP '^[0-9]+$'
            """)
            cur.execute("ALTER TABLE reviews MODIFY product_id INT")
        cur.execute("""
            UPDATE reviews r
            LEFT JOIN products p ON p.id = r.product_id
               SET r.product_id = NULL
             WHERE r.product_id IS NOT NULL
               AND p.id IS NULL
        """)
        cur.execute("""
            SELECT CONSTRAINT_NAME
              FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
             WHERE TABLE_SCHEMA = %s
               AND TABLE_NAME = 'reviews'
               AND COLUMN_NAME = 'product_id'
               AND REFERENCED_TABLE_NAME = 'products'
        """, (DB_NAME,))
        if not cur.fetchone():
            cur.execute("""
                ALTER TABLE reviews
                ADD CONSTRAINT fk_reviews_product
                FOREIGN KEY (product_id) REFERENCES products(id)
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


def get_products() -> list[dict]:
    con = get_db()
    try:
        cur = con.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT
                p.id,
                p.name,
                p.price,
                p.description,
                p.badge,
                ROUND(AVG(r.rating), 1) AS average_rating,
                COUNT(r.id) AS review_count
              FROM products p
              LEFT JOIN reviews r ON r.product_id = p.id
             GROUP BY p.id, p.name, p.price, p.description, p.badge
             ORDER BY p.id
        """)
        return cur.fetchall()
    finally:
        con.close()


def get_product(product_id: int) -> dict | None:
    con = get_db()
    try:
        cur = con.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT
                p.id,
                p.name,
                p.price,
                p.description,
                p.badge,
                ROUND(AVG(r.rating), 1) AS average_rating,
                COUNT(r.id) AS review_count
              FROM products p
              LEFT JOIN reviews r ON r.product_id = p.id
             WHERE p.id = %s
             GROUP BY p.id, p.name, p.price, p.description, p.badge
        """, (product_id,))
        return cur.fetchone()
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


def insert_review(product_id: int, review: str, rating: float | None) -> int:
    con = get_db()
    try:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO reviews (product_id, review, rating) VALUES (%s, %s, %s)",
            (product_id, review, rating),
        )
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


def get_reviews_by_product(product_id: int) -> list[dict]:
    con = get_db()
    try:
        cur = con.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT id, product_id, review, rating, agent_aspect, agent_label, agent_evidence,
                   verdict, reason_code, retry_count, updated_at
              FROM reviews
             WHERE product_id = %s
             ORDER BY updated_at DESC
        """, (product_id,))
        return cur.fetchall()
    finally:
        con.close()
