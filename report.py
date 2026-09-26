#!/usr/bin/env python3
"""Ad-hoc lookup: packages and pay for one driver over a date range.

    python report.py Иван 2026-09-14 2026-09-26
    python report.py 5551234567 2026-09-14          # single day
    python report.py --list                         # who's in the whitelist

Read-only: it runs SELECTs only and never writes to the database.
Needs DATABASE_URL in the environment (or run it via `railway run`).
"""
import os
import sys
from datetime import datetime

from config import COMPANY_RATE
from data import APP_DAY_NAMES, app_day, get_user_period_data, get_whitelist
from rates import get_rate_card

USAGE = __doc__


def fail(msg):
    print(msg)
    raise SystemExit(1)


def resolve_driver(arg: str, whitelist: dict) -> int:
    """Accepts a telegram id or a (partial, case-insensitive) name."""
    if arg.isdigit():
        uid = int(arg)
        if uid not in whitelist:
            fail(f"No driver with id {uid}. Use --list to see the whitelist.")
        return uid

    matches = [uid for uid, name in whitelist.items() if arg.lower() in name.lower()]
    if not matches:
        fail(f"No driver matching '{arg}'. Use --list to see the whitelist.")
    if len(matches) > 1:
        names = ", ".join(f"{whitelist[uid]} ({uid})" for uid in matches)
        fail(f"'{arg}' matches several drivers: {names}. Be more specific or pass the id.")
    return matches[0]


def parse_date(arg: str):
    try:
        return datetime.strptime(arg, "%Y-%m-%d").date()
    except ValueError:
        fail(f"Bad date '{arg}'. Use YYYY-MM-DD.")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return
    if not os.getenv("DATABASE_URL"):
        fail("DATABASE_URL is not set. Export it, or run this through `railway run`.")

    whitelist = get_whitelist()

    if argv[0] == "--list":
        for uid, name in whitelist.items():
            card = get_rate_card(uid)
            print(f"{uid}  {name}  —  {card.label()}")
        return

    if len(argv) not in (2, 3):
        print(USAGE)
        raise SystemExit(1)

    uid = resolve_driver(argv[0], whitelist)
    name = whitelist[uid]
    start = parse_date(argv[1])
    end = parse_date(argv[2]) if len(argv) == 3 else start
    if end < start:
        start, end = end, start

    card = get_rate_card(uid)
    period = get_user_period_data(uid, start, end)

    span = (start.strftime("%b %-d, %Y") if start == end
            else f"{start.strftime('%b %-d')} – {end.strftime('%b %-d, %Y')}")
    print(f"{name} — {span}")
    print(f"rate: {card.label()}")
    print()

    if not period:
        print("No data for this period.")
        return

    total = 0
    pay = 0.0
    days_worked = 0
    per_route = {}
    for day, routes in sorted(period.items()):
        day_total = sum(routes.values())
        total += day_total
        pay += card.pay(routes)
        days_worked += 1
        detail = "  ".join(
            f"R{route}: {count} @ ${card.for_route(route):.2f}"
            for route, count in sorted(routes.items())
        )
        for route, count in routes.items():
            per_route[route] = per_route.get(route, 0) + count
        print(f"{APP_DAY_NAMES[app_day(day)]} {day.strftime('%b %-d')}  {day_total:>4} pkgs   {detail}")

    revenue = total * COMPANY_RATE
    print()
    print("by route:  " + "   ".join(
        f"R{route}: {count} = ${count * card.for_route(route):.2f}"
        for route, count in sorted(per_route.items())
    ))
    print(f"days worked:     {days_worked}")
    print(f"packages:        {total}")
    print(f"driver pay:      ${pay:.2f}")
    print(f"company revenue: ${revenue:.2f}  (@ ${COMPANY_RATE:.2f}/pkg)")
    print(f"profit:          ${revenue - pay:.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
