import json

import pymysql
import pymysql.cursors

from env import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

SAMPLE_PRODUCTS = [
    (1,  "히알루론산 수분 크림 50ml",       24900, "끈적임 없이 촉촉하게 채워주는 고보습 크림입니다.",              "특가"),
    (2,  "로즈힙 페이셜 오일 30ml",          32000, "풍부한 비타민이 피부 결을 개선해주는 드라이 오일입니다.",       None),
    (3,  "세라마이드 앰플 에센스 50ml",       28500, "피부 장벽을 강화하고 수분을 가두어 주는 앰플입니다.",          "NEW"),
    (4,  "알로에 수딩 젤 300ml",              9900,  "자극받은 피부를 즉각 진정시켜 주는 대용량 수딩 젤입니다.",     None),
    (5,  "콜라겐 보습 마스크팩 10매",         15000, "탄력과 수분을 한 번에 챙길 수 있는 집중 보습 마스크팩입니다.", "특가"),
    (6,  "라벤더 바디로션 200ml",             13500, "은은한 라벤더 향으로 피부를 부드럽고 촉촉하게 가꿔줍니다.",   None),
    (7,  "시어버터 핸드크림 50ml",             8900,  "건조한 손을 집중 케어해주는 진한 시어버터 핸드크림입니다.",   "NEW"),
    (8,  "자스민 퍼퓸 바디워시 300ml",        16800, "풍성한 거품과 은은한 자스민 향이 기분을 환기시켜줍니다.",     None),
    (9,  "녹차 수분 토너 150ml",              19000, "피부결을 정돈하고 청량한 녹차 성분으로 수분을 보충합니다.",   "NEW"),
    (10, "레티놀 나이트크림 50ml",            38000, "잠자는 동안 피부를 재생시키는 고농도 레티놀 크림입니다.",     "특가"),
    (11, "비타민E 선크림 SPF50+ 50ml",        22000, "자외선 차단과 동시에 보습까지 챙겨주는 데일리 선크림입니다.", None),
    (12, "펩타이드 아이크림 20ml",            31500, "눈가 잔주름과 다크서클을 개선해주는 고기능 아이크림입니다.",  None),
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
                id         INT PRIMARY KEY AUTO_INCREMENT,
                product_id INT,
                review     TEXT,
                rating     FLOAT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_reviews_product
                    FOREIGN KEY (product_id) REFERENCES products(id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS review_analyses (
                id             INT PRIMARY KEY AUTO_INCREMENT,
                review_id      INT NOT NULL,
                agent_aspect   TEXT,
                agent_label    TEXT,
                agent_evidence TEXT,
                verdict        VARCHAR(20),
                reason_code    VARCHAR(50),
                retry_count    INT DEFAULT 0,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_analyses_review
                    FOREIGN KEY (review_id) REFERENCES reviews(id)
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


def save_analysis(review_id: int, state: dict):
    items         = (state.get("analyzer_result") or {}).get("items", [])
    critic_result = state.get("critic_result") or {}

    con = get_db()
    try:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO review_analyses
                (review_id, agent_aspect, agent_label, agent_evidence,
                 verdict, reason_code, retry_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            review_id,
            json.dumps([i.get("aspect",   "") for i in items], ensure_ascii=False),
            json.dumps([i.get("label",    0)  for i in items], ensure_ascii=False),
            json.dumps([i.get("evidence", "") for i in items], ensure_ascii=False),
            critic_result.get("verdict"),
            state.get("reason_code"),
            state.get("retry_count", 0),
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
            SELECT id, product_id, review, rating, updated_at
              FROM reviews
             WHERE product_id = %s
             ORDER BY updated_at DESC
        """, (product_id,))
        return cur.fetchall()
    finally:
        con.close()
