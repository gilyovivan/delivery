import logging
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from data import (
    init_db, record_delivery, get_week_data, set_driver_rate, get_driver_rate,
    get_all_rates, app_day, APP_DAY_NAMES, get_user_period_data,
    get_whitelist, add_driver, seed_drivers_from_whitelist
)
from config import (
    BOT_TOKEN, WHITELIST as SEED_WHITELIST, COMPANY_RATE, DEFAULT_DRIVER_RATE,
    PACIFIC_TZ, REPORT_CHAT_ID, ADMIN_ID, VALID_ROUTES
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"ADMIN_ID loaded: {ADMIN_ID} (type: {type(ADMIN_ID).__name__})")
logger.info(f"REPORT_CHAT_ID loaded: {REPORT_CHAT_ID}")

# WHITELIST now lives in the DB (drivers table) so it can be edited at
# runtime from the admin panel. SEED_WHITELIST (from env) only bootstraps
# it once on first startup.
WHITELIST = {}


def refresh_whitelist():
    global WHITELIST
    WHITELIST = get_whitelist()
    logger.info(f"WHITELIST loaded from DB: {WHITELIST}")


def format_date(dt: datetime) -> str:
    return dt.strftime("%b %-d")


def is_admin(user_id: int) -> bool:
    return int(user_id) == int(ADMIN_ID)


def is_authorized(user_id: int) -> bool:
    return user_id in WHITELIST or is_admin(user_id)


def get_week_start(dt: datetime) -> datetime:
    days_since_sunday = (dt.weekday() + 1) % 7
    return dt - timedelta(days=days_since_sunday)


def build_driver_report_text(name, user_data, driver_rate, week_start):
    week_end = week_start + timedelta(days=6)
    week_range = f"{format_date(week_start)} – {format_date(week_end)}, {week_start.year}"
    lines = [f"📋 *Weekly Report — {name}*", f"🗓 {week_range}\n"]
    total = 0
    for day_num, routes in sorted(user_data.items()):
        day_total = sum(routes.values())
        total += day_total
        day_dt = week_start + timedelta(days=day_num)
        lines.append(f"*{APP_DAY_NAMES[day_num]} {format_date(day_dt)}* — {day_total} packages")
        for route, count in sorted(routes.items()):
            lines.append(f"  Route {route}: {count}")
    lines.append(f"\n📦 Total: *{total}* packages")
    lines.append(f"💰 Your earnings: *${total * driver_rate:.2f}*")
    return "\n".join(lines)


def build_driver_block(name, items, driver_rate, show_revenue=False):
    """items: list of (label, routes_dict), one per day, already sorted."""
    lines = [f"👤 *{name}*  (rate: ${driver_rate:.2f}/pkg)"]
    user_total = 0
    for label, routes in items:
        day_total = sum(routes.values())
        user_total += day_total
        lines.append(f"  *{label}* — {day_total} pkgs")
        for route, count in sorted(routes.items()):
            lines.append(f"    Route {route}: {count}")
    company_rev = user_total * COMPANY_RATE
    driver_cost = user_total * driver_rate
    profit = company_rev - driver_cost
    lines.append(f"  Packages: *{user_total}*")
    if show_revenue:
        lines.append(f"  Company revenue: ${company_rev:.2f}")
    lines.append(f"  Driver pay: *${driver_cost:.2f}*")
    if show_revenue:
        lines.append(f"  Your profit: *${profit:.2f}*")
    return lines, user_total, company_rev, driver_cost


def build_admin_driver_block(name, user_data, driver_rate, week_start, show_revenue=False):
    items = []
    for day_num, routes in sorted(user_data.items()):
        day_dt = week_start + timedelta(days=day_num)
        items.append((f"{APP_DAY_NAMES[day_num]} {format_date(day_dt)}", routes))
    return build_driver_block(name, items, driver_rate, show_revenue)


def build_period_driver_block(name, period_data, driver_rate, show_revenue=False):
    items = [(d.strftime("%a %b %-d"), routes) for d, routes in sorted(period_data.items())]
    return build_driver_block(name, items, driver_rate, show_revenue)


# ─── /start ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("You don't have access to this bot.")
        return

    name = WHITELIST.get(user_id, "Admin")
    routes_str = ", ".join(str(r) for r in sorted(VALID_ROUTES))

    msg = (
        f"Добро пожаловать в Delivery Stat Tracker, {name}!\n\n"
        f"Как отправить данные:\n"
        f"Отправь номер маршрута и количество посылок через запятую.\n\n"
        f"Пример: 2, 63\n"
        f"Это значит: Маршрут 2, 63 посылки доставлено.\n\n"
        f"Доступные маршруты: {routes_str}\n\n"
        f"Если отправишь данные повторно за тот же день — новое число заменит старое."
    )

    if is_admin(user_id):
        keyboard = [
            [KeyboardButton("My Stats"), KeyboardButton("My Report")],
            [KeyboardButton("Last Week"), KeyboardButton("Admin Panel")],
        ]
    else:
        keyboard = [
            [KeyboardButton("My Stats"), KeyboardButton("My Report")],
            [KeyboardButton("Last Week")],
        ]

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(msg, reply_markup=reply_markup)


# ─── Admin Panel inline menu ──────────────────────────────────────────────────

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.message else update.callback_query.from_user.id
    if not is_admin(user_id):
        if update.message:
            await update.message.reply_text("Admin only.")
        return

    keyboard = [
        [InlineKeyboardButton("📋 This week — All drivers", callback_data="admin_week_current_ALL")],
        [InlineKeyboardButton("📋 Last week — All drivers", callback_data="admin_week_last_ALL")],
    ]
    for uid, name in WHITELIST.items():
        keyboard.append([
            InlineKeyboardButton(f"This week — {name}", callback_data=f"admin_week_current_{uid}"),
            InlineKeyboardButton(f"Last week — {name}", callback_data=f"admin_week_last_{uid}"),
        ])

    keyboard.append([InlineKeyboardButton("📅 Custom period", callback_data="admin_customperiod")])
    keyboard.append([InlineKeyboardButton("✏️ Manual entry (backdate)", callback_data="admin_manualentry")])
    keyboard.append([InlineKeyboardButton("👥 Manage Drivers", callback_data="admin_managedrivers")])

    markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text("Admin Panel:", reply_markup=markup)
    else:
        await update.callback_query.message.edit_text("Admin Panel:", reply_markup=markup)


async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not is_admin(user_id):
        await query.message.reply_text("Admin only.")
        return

    data = query.data
    now = datetime.now(PACIFIC_TZ)

    if data == "admin_back":
        await admin_panel(update, context)
        return

    if data == "admin_customperiod":
        keyboard = [
            [InlineKeyboardButton(name, callback_data=f"admin_cp_pick_{uid}")]
            for uid, name in WHITELIST.items()
        ]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
        await query.message.edit_text("Select a driver:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("admin_cp_pick_"):
        uid = int(data.rsplit("_", 1)[-1])
        name = WHITELIST.get(uid, "Driver")
        context.user_data["admin_pending"] = {"action": "period", "uid": uid}
        await query.message.edit_text(
            f"Send a date or date range for *{name}*:\n"
            f"• Single day: `2026-07-10`\n"
            f"• Range: `2026-07-01 2026-07-10`",
            parse_mode='Markdown'
        )
        return

    if data == "admin_manualentry":
        keyboard = [
            [InlineKeyboardButton(name, callback_data=f"admin_me_pick_{uid}")]
            for uid, name in WHITELIST.items()
        ]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
        await query.message.edit_text("Select a driver to backdate:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("admin_me_pick_"):
        uid = int(data.rsplit("_", 1)[-1])
        name = WHITELIST.get(uid, "Driver")
        routes_str = ", ".join(str(r) for r in sorted(VALID_ROUTES))
        context.user_data["admin_pending"] = {"action": "manual_entry", "uid": uid}
        await query.message.edit_text(
            f"Send date, route, packages for *{name}*:\n"
            f"`2026-08-02, 2, 60`\n\n"
            f"Available routes: {routes_str}",
            parse_mode='Markdown'
        )
        return

    if data == "admin_managedrivers":
        all_rates = get_all_rates()
        lines = ["*Manage Drivers:*\n"]
        keyboard = []
        for uid, name in WHITELIST.items():
            rate = all_rates.get(uid, DEFAULT_DRIVER_RATE)
            tag = " (default)" if uid not in all_rates else ""
            lines.append(f"  *{name}* — ${rate:.2f}/pkg{tag}")
            lines.append(f"  ID: `{uid}`\n")
            keyboard.append([InlineKeyboardButton(f"✏️ {name} — ${rate:.2f}", callback_data=f"admin_rate_pick_{uid}")])
        lines.append(f"Company rate: *${COMPANY_RATE:.2f}/pkg*")
        keyboard.append([InlineKeyboardButton("➕ Add driver", callback_data="admin_adddriver")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
        await query.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if data.startswith("admin_rate_pick_"):
        uid = int(data.rsplit("_", 1)[-1])
        name = WHITELIST.get(uid, "Driver")
        current_rate = get_driver_rate(uid, DEFAULT_DRIVER_RATE)
        context.user_data["admin_pending"] = {"action": "edit_rate", "uid": uid}
        await query.message.edit_text(
            f"Send new rate for *{name}* (current: ${current_rate:.2f}/pkg):\nExample: `0.85`",
            parse_mode='Markdown'
        )
        return

    if data == "admin_adddriver":
        context.user_data["admin_pending"] = {"action": "add_driver"}
        await query.message.edit_text(
            "Send the new driver's Telegram ID and name:\n"
            "`5551234567, Alex`\n\n"
            "The driver can get their ID from @userinfobot on Telegram.",
            parse_mode='Markdown'
        )
        return

    if data.startswith("admin_week_"):
        parts = data.split("_")
        period = parts[2]
        target = "_".join(parts[3:])

        ref_dt = (now - timedelta(days=7)) if period == "last" else now
        week_start = get_week_start(ref_dt)
        week_end = week_start + timedelta(days=6)
        week_range = f"{format_date(week_start)} – {format_date(week_end)}, {week_start.year}"
        week_data = get_week_data(ref_dt)

        if target == "ALL":
            lines = [f"*ADMIN REPORT*", f"{week_range}\n"]
            grand_packages = 0
            grand_company_revenue = 0.0
            grand_driver_cost = 0.0
            any_data = False

            for uid, name in WHITELIST.items():
                user_data = week_data.get(uid, {})
                if not user_data:
                    continue
                any_data = True
                driver_rate = get_driver_rate(uid, DEFAULT_DRIVER_RATE)
                block, user_total, company_rev, driver_cost = build_admin_driver_block(name, user_data, driver_rate, week_start, show_revenue=True)
                lines += block
                lines.append("")
                grand_packages += user_total
                grand_company_revenue += company_rev
                grand_driver_cost += driver_cost

            if not any_data:
                await query.message.reply_text("No data for this period.")
                return

            grand_profit = grand_company_revenue - grand_driver_cost
            lines.append("─────────────────")
            lines.append(f"Total packages: *{grand_packages}*")
            lines.append(f"Company revenue: ${grand_company_revenue:.2f}")
            lines.append(f"Total driver pay: ${grand_driver_cost:.2f}")
            lines.append(f"Your profit: *${grand_profit:.2f}*")

        else:
            uid = int(target)
            name = WHITELIST.get(uid, "Driver")
            user_data = week_data.get(uid, {})
            if not user_data:
                await query.message.reply_text(f"No data for {name} this period.")
                return
            driver_rate = get_driver_rate(uid, DEFAULT_DRIVER_RATE)
            block, user_total, company_rev, driver_cost = build_admin_driver_block(name, user_data, driver_rate, week_start, show_revenue=False)
            profit = company_rev - driver_cost
            lines = [f"*{name} — {week_range}*\n"] + block
            lines.append(f"\nYour profit: *${profit:.2f}*")

        await query.message.reply_text("\n".join(lines), parse_mode='Markdown')


# ─── Admin: custom period lookup ─────────────────────────────────────────────

async def handle_period_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int):
    text = update.message.text.strip()
    matches = re.findall(r"\d{4}-\d{2}-\d{2}", text)

    if not matches or len(matches) > 2:
        await update.message.reply_text(
            "Couldn't parse that. Send a date like `2026-07-10` or a range like "
            "`2026-07-01 2026-07-10`, or open Admin Panel → Custom period again.",
            parse_mode='Markdown'
        )
        return

    try:
        dates = sorted(datetime.strptime(m, "%Y-%m-%d").date() for m in matches)
    except ValueError:
        await update.message.reply_text("Invalid date(s). Use format YYYY-MM-DD.")
        return

    start_date, end_date = dates[0], dates[-1]
    name = WHITELIST.get(uid, "Driver")
    driver_rate = get_driver_rate(uid, DEFAULT_DRIVER_RATE)
    period_data = get_user_period_data(uid, start_date, end_date)

    range_str = (
        start_date.strftime("%b %-d, %Y") if start_date == end_date
        else f"{start_date.strftime('%b %-d')} – {end_date.strftime('%b %-d, %Y')}"
    )

    if not period_data:
        await update.message.reply_text(f"No data for {name} on {range_str}.")
        return

    block, user_total, company_rev, driver_cost = build_period_driver_block(
        name, period_data, driver_rate, show_revenue=True
    )
    profit = company_rev - driver_cost
    lines = [f"*{range_str}*\n"] + block
    lines.append(f"\nYour profit: *${profit:.2f}*")

    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')


async def handle_manual_entry_input(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int):
    text = update.message.text.strip()
    routes_str = ", ".join(str(r) for r in sorted(VALID_ROUTES))

    date_match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if not date_match:
        await update.message.reply_text(
            "Couldn't parse that. Send: date, route, packages\nExample: `2026-08-02, 2, 60`",
            parse_mode='Markdown'
        )
        return

    try:
        entry_date = datetime.strptime(date_match.group(), "%Y-%m-%d").date()
    except ValueError:
        await update.message.reply_text("Invalid date. Use format YYYY-MM-DD.")
        return

    rest = text[:date_match.start()] + text[date_match.end():]
    nums = re.findall(r"\d+", rest)
    if len(nums) != 2:
        await update.message.reply_text(
            "Couldn't parse route/packages. Send: date, route, packages\nExample: `2026-08-02, 2, 60`",
            parse_mode='Markdown'
        )
        return

    route, count = int(nums[0]), int(nums[1])
    if route not in VALID_ROUTES:
        await update.message.reply_text(f"Route {route} doesn't exist. Available: {routes_str}")
        return
    if count < 0:
        await update.message.reply_text("Packages must be a positive number.")
        return

    name = WHITELIST.get(uid, "Driver")
    existing_day = get_user_period_data(uid, entry_date, entry_date).get(entry_date, {})
    old_count = existing_day.get(route)

    record_delivery(uid, route, count, entry_date)

    day_name = APP_DAY_NAMES[app_day(entry_date)]
    date_disp = entry_date.strftime("%b %-d, %Y")
    note = f" (was {old_count})" if old_count is not None else ""
    await update.message.reply_text(
        f"✅ Saved for {name}: {day_name} {date_disp} — Route {route}: {count} packages{note}"
    )


# ─── Admin: manage drivers ────────────────────────────────────────────────────

async def handle_edit_rate_input(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int):
    text = update.message.text.strip().replace(",", ".")
    try:
        rate = float(text)
        if rate <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Invalid rate. Send a positive number, e.g. 0.85")
        return

    set_driver_rate(uid, rate)
    name = WHITELIST.get(uid, "Driver")
    await update.message.reply_text(f"✅ Rate updated: {name} → ${rate:.2f}/pkg")


async def handle_add_driver_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    match = re.match(r"^(\d+)\s*,\s*(.+)$", text)
    if not match:
        await update.message.reply_text(
            "Couldn't parse that. Send: telegram_id, name\nExample: `5551234567, Alex`",
            parse_mode='Markdown'
        )
        return

    new_uid = int(match.group(1))
    name = match.group(2).strip()
    if not name:
        await update.message.reply_text("Name can't be empty.")
        return

    is_rename = new_uid in WHITELIST
    add_driver(new_uid, name)
    refresh_whitelist()

    if is_rename:
        await update.message.reply_text(f"✅ Updated driver: {name} (ID {new_uid})")
    else:
        await update.message.reply_text(
            f"✅ Added driver: {name} (ID {new_uid})\nThey can now send /start to begin."
        )


async def handle_admin_pending_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending = context.user_data.pop("admin_pending")
    action = pending["action"]
    if action == "period":
        await handle_period_date_input(update, context, pending["uid"])
    elif action == "manual_entry":
        await handle_manual_entry_input(update, context, pending["uid"])
    elif action == "edit_rate":
        await handle_edit_rate_input(update, context, pending["uid"])
    elif action == "add_driver":
        await handle_add_driver_input(update, context)


# ─── Handle messages & keyboard buttons ──────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("You don't have access to this bot.")
        return

    text = update.message.text.strip()

    if is_admin(user_id) and "admin_pending" in context.user_data:
        if text not in ("My Stats", "My Report", "Last Week", "Admin Panel"):
            await handle_admin_pending_input(update, context)
            return
        context.user_data.pop("admin_pending", None)

    if text == "My Stats":
        await my_stats(update, context)
        return
    if text == "My Report":
        await report_command(update, context)
        return
    if text == "Last Week":
        await last_report_command(update, context)
        return
    if text == "Admin Panel":
        await admin_panel(update, context)
        return

    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 2:
        routes_str = ", ".join(str(r) for r in sorted(VALID_ROUTES))
        await update.message.reply_text(
            f"Wrong format. Send: route, packages\nExample: 2, 63\nAvailable routes: {routes_str}"
        )
        return

    try:
        route = int(parts[0])
        count = int(parts[1])
        if count < 0 or route < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Both values must be positive numbers.\nExample: 2, 63")
        return

    if route not in VALID_ROUTES:
        routes_str = ", ".join(str(r) for r in sorted(VALID_ROUTES))
        await update.message.reply_text(f"Route {route} doesn't exist. Available: {routes_str}")
        return

    now = datetime.now(PACIFIC_TZ)
    name = WHITELIST.get(user_id, "Admin")
    driver_rate = get_driver_rate(user_id, DEFAULT_DRIVER_RATE)
    earnings = count * driver_rate
    day_name = APP_DAY_NAMES[app_day(now)]
    date_str = format_date(now)

    record_delivery(user_id, route, count, now)

    await update.message.reply_text(
        f"Saved! {name}, {day_name} {date_str} — Route {route}: {count} packages = ${earnings:.2f}"
    )


# ─── /mystats ────────────────────────────────────────────────────────────────

async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("You don't have access to this bot.")
        return

    name = WHITELIST.get(user_id, "Admin")
    now = datetime.now(PACIFIC_TZ)
    week_data = get_week_data(now)
    user_data = week_data.get(user_id, {})

    if not user_data:
        await update.message.reply_text(f"{name}, no data for this week yet.")
        return

    driver_rate = get_driver_rate(user_id, DEFAULT_DRIVER_RATE)
    week_start = get_week_start(now)
    lines = [f"Your week, {name}:\n"]
    total = 0

    for day_num, routes in sorted(user_data.items()):
        day_total = sum(routes.values())
        total += day_total
        day_dt = week_start + timedelta(days=day_num)
        lines.append(f"{APP_DAY_NAMES[day_num]} {format_date(day_dt)} — {day_total} packages")
        for route, count in sorted(routes.items()):
            lines.append(f"  Route {route}: {count}")

    lines.append(f"\nTotal: {total} packages")
    lines.append(f"Your earnings: ${total * driver_rate:.2f}  (${driver_rate}/pkg)")

    await update.message.reply_text("\n".join(lines))


# ─── /report ─────────────────────────────────────────────────────────────────

async def driver_report(context, chat_id, user_id, week_data, now):
    name = WHITELIST.get(user_id, "Driver")
    user_data = week_data.get(user_id, {})
    driver_rate = get_driver_rate(user_id, DEFAULT_DRIVER_RATE)
    week_start = get_week_start(now)

    if not user_data:
        await context.bot.send_message(chat_id=chat_id, text=f"{name}, no data for this week yet.")
        return

    text = build_driver_report_text(name, user_data, driver_rate, week_start)
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("You don't have access to this bot.")
        return
    now = datetime.now(PACIFIC_TZ)
    week_data = get_week_data(now)
    await driver_report(context, update.effective_chat.id, user_id, week_data, now)


async def last_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("You don't have access to this bot.")
        return
    now = datetime.now(PACIFIC_TZ)
    last_week = now - timedelta(days=7)
    week_data = get_week_data(last_week)
    await driver_report(context, update.effective_chat.id, user_id, week_data, last_week)


# ─── /adminreport ────────────────────────────────────────────────────────────

async def admin_report(context, chat_id, now=None):
    if now is None:
        now = datetime.now(PACIFIC_TZ)

    week_data = get_week_data(now)
    week_start = get_week_start(now)
    week_end = week_start + timedelta(days=6)
    week_range = f"{format_date(week_start)} – {format_date(week_end)}, {now.year}"

    lines = [f"ADMIN WEEKLY REPORT", f"{week_range}\n"]
    grand_packages = 0
    grand_company_revenue = 0.0
    grand_driver_cost = 0.0
    any_data = False

    for user_id_int, name in WHITELIST.items():
        user_data = week_data.get(user_id_int, {})
        if not user_data:
            continue
        any_data = True
        driver_rate = get_driver_rate(user_id_int, DEFAULT_DRIVER_RATE)
        block, user_total, company_rev, driver_cost = build_admin_driver_block(name, user_data, driver_rate, week_start, show_revenue=True)
        lines += block
        lines.append("")
        grand_packages += user_total
        grand_company_revenue += company_rev
        grand_driver_cost += driver_cost

    if not any_data:
        await context.bot.send_message(chat_id=chat_id, text="No data for this week yet.")
        return

    grand_profit = grand_company_revenue - grand_driver_cost
    lines.append("─────────────────")
    lines.append(f"Total packages: {grand_packages}")
    lines.append(f"Company revenue: ${grand_company_revenue:.2f}")
    lines.append(f"Total driver pay: ${grand_driver_cost:.2f}")
    lines.append(f"Your profit: ${grand_profit:.2f}")

    await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode='Markdown')


async def admin_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("Admin only.")
        return
    await admin_report(context, update.effective_chat.id)


async def last_admin_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("Admin only.")
        return
    now = datetime.now(PACIFIC_TZ)
    last_week = now - timedelta(days=7)
    await admin_report(context, update.effective_chat.id, last_week)


# ─── /setrate ────────────────────────────────────────────────────────────────

async def set_rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("Admin only.")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Usage: /setrate user_id rate\nExample: /setrate 123456789 0.80")
        return

    try:
        target_id = int(args[0])
        rate = float(args[1])
        if rate <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Invalid user_id or rate.")
        return

    if target_id not in WHITELIST:
        await update.message.reply_text(f"User {target_id} not found in whitelist.")
        return

    set_driver_rate(target_id, rate)
    name = WHITELIST[target_id]
    await update.message.reply_text(f"Rate updated! {name} -> ${rate:.2f}/package")


# ─── Scheduled reports ───────────────────────────────────────────────────────

async def scheduled_reports(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Sending scheduled weekly reports...")
    now = datetime.now(PACIFIC_TZ)
    last_saturday = now - timedelta(days=1)
    week_data = get_week_data(last_saturday)

    for uid in WHITELIST:
        try:
            await driver_report(context, uid, uid, week_data, last_saturday)
        except Exception as e:
            logger.warning(f"Could not send report to user {uid}: {e}")

    if REPORT_CHAT_ID:
        await admin_report(context, REPORT_CHAT_ID, last_saturday)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    init_db()
    seed_drivers_from_whitelist(SEED_WHITELIST)
    refresh_whitelist()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mystats", my_stats))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("lastreport", last_report_command))
    app.add_handler(CommandHandler("adminreport", admin_report_command))
    app.add_handler(CommandHandler("lastadminreport", last_admin_report_command))
    app.add_handler(CommandHandler("setrate", set_rate_command))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(handle_admin_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = AsyncIOScheduler(timezone=PACIFIC_TZ)
    scheduler.add_job(
        scheduled_reports,
        trigger='cron',
        day_of_week='sun',
        hour=19,
        minute=30,
        args=[app]
    )
    scheduler.start()

    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
