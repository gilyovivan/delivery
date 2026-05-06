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
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    user_id     BIGINT NOT NULL,
                    week_key    TEXT NOT NULL,
                    day_num     SMALLINT NOT NULL,
                    route       SMALLINT NOT NULL,
                    count       INTEGER NOT NULL,
                    updated_at  TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (user_id, week_key, day_num, route)
                )
            """)
        conn.commit()
    logger.info("DB initialized.")


def get_week_key(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def record_delivery(user_id: int, route: int, count: int, dt: datetime):
    """Upsert delivery count for a user/route/day. Overwrites if exists."""
    week_key = get_week_key(dt)
    day_num = dt.weekday()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO deliveries (user_id, week_key, day_num, route, count, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id, week_key, day_num, route)
                DO UPDATE SET count = EXCLUDED.count, updated_at = NOW()
            """, (user_id, week_key, day_num, route, count))
        conn.commit()
    logger.info(f"Recorded: user={user_id}, week={week_key}, day={day_num}, route={route}, count={count}")


def get_week_data(dt: datetime) -> dict:
    """
    Returns nested dict:
    { user_id_int: { day_num_int: { route_int: count } } }
    """
    week_key = get_week_key(dt)
    result = {}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, day_num, route, count
                FROM deliveries
                WHERE week_key = %s
                ORDER BY user_id, day_num, route
            """, (week_key,))
            rows = cur.fetchall()

    for row in rows:
        uid = row["user_id"]
        day = row["day_num"]
        route = row["route"]
        if uid not in result:
            result[uid] = {}
        if day not in result[uid]:
            result[uid][day] = {}
        result[uid][day][route] = row["count"]

    return result
