import os
import logging
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    """Create table if it doesn't exist."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    user_id     BIGINT NOT NULL,
                    week_key    TEXT NOT NULL,
                    day_num     SMALLINT NOT NULL,
                    count       INTEGER NOT NULL,
                    updated_at  TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (user_id, week_key, day_num)
                )
            """)
        conn.commit()
    logger.info("DB initialized.")


def get_week_key(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def record_delivery(user_id: int, count: int, dt: datetime):
    week_key = get_week_key(dt)
    day_num = dt.weekday()  # 0=Mon, 6=Sun

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO deliveries (user_id, week_key, day_num, count, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (user_id, week_key, day_num)
                DO UPDATE SET count = EXCLUDED.count, updated_at = NOW()
            """, (user_id, week_key, day_num, count))
        conn.commit()
    logger.info(f"Recorded: user={user_id}, week={week_key}, day={day_num}, count={count}")


def get_week_data(dt: datetime) -> dict:
    """
    Returns: { user_id_int: { day_num: count } }
    """
    week_key = get_week_key(dt)
    result = {}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, day_num, count
                FROM deliveries
                WHERE week_key = %s
                ORDER BY user_id, day_num
            """, (week_key,))
            rows = cur.fetchall()

    for row in rows:
        uid = row["user_id"]
        if uid not in result:
            result[uid] = {}
        result[uid][row["day_num"]] = row["count"]

    return result
