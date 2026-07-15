import os
import logging
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

# Week runs Sun(0) Mon(1) Tue(2) Wed(3) Thu(4) Fri(5) Sat(6)
# Python weekday(): Mon=0 ... Sun=6
# We remap: Sun->0, Mon->1, ..., Sat->6
PYTHON_TO_APP_DAY = {6: 0, 0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6}
APP_DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def app_day(dt: datetime) -> int:
    return PYTHON_TO_APP_DAY[dt.weekday()]


def get_week_key(dt: datetime) -> str:
    """
    Week key based on Sun-Sat week.
    Sunday starts a new week, so we use Sunday's date as the week anchor.
    """
    days_since_sunday = (dt.weekday() + 1) % 7
    sunday = dt - timedelta(days=days_since_sunday)
    return sunday.strftime("%Y-W%m%d")


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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS driver_rates (
                    user_id     BIGINT PRIMARY KEY,
                    rate        NUMERIC(6,2) NOT NULL,
                    updated_at  TIMESTAMP DEFAULT NOW()
                )
            """)
        conn.commit()
    logger.info("DB initialized.")


def record_delivery(user_id: int, route: int, count: int, dt: datetime):
    week_key = get_week_key(dt)
    day_num = app_day(dt)
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
    """Returns: { user_id_int: { day_num_int: { route_int: count } } }"""
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


def set_driver_rate(user_id: int, rate: float):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO driver_rates (user_id, rate, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (user_id)
                DO UPDATE SET rate = EXCLUDED.rate, updated_at = NOW()
            """, (user_id, rate))
        conn.commit()


def get_driver_rate(user_id: int, default: float) -> float:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT rate FROM driver_rates WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
    return float(row["rate"]) if row else default


def get_all_rates() -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, rate FROM driver_rates")
            rows = cur.fetchall()
    return {row["user_id"]: float(row["rate"]) for row in rows}


def get_user_period_data(user_id: int, start_date, end_date) -> dict:
    """
    Returns deliveries for one user within [start_date, end_date] inclusive
    (start_date/end_date are date objects), regardless of week boundaries.
    Returns: { date_obj: { route_int: count } }
    """
    day_map = {}
    week_keys = set()
    d = start_date
    while d <= end_date:
        week_key = get_week_key(d)
        day_num = app_day(d)
        day_map[(week_key, day_num)] = d
        week_keys.add(week_key)
        d += timedelta(days=1)

    if not week_keys:
        return {}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT week_key, day_num, route, count
                FROM deliveries
                WHERE user_id = %s AND week_key = ANY(%s)
            """, (user_id, list(week_keys)))
            rows = cur.fetchall()

    result = {}
    for row in rows:
        key = (row["week_key"], row["day_num"])
        if key not in day_map:
            continue
        d = day_map[key]
        result.setdefault(d, {})[row["route"]] = row["count"]
    return result
