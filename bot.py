import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from data import init_db, record_delivery, get_week_data, set_driver_rate, get_driver_rate, get_all_rates, app_day, APP_DAY_NAMES
from config import (
    BOT_TOKEN, WHITELIST, COMPANY_RATE, DEFAULT_DRIVER_RATE,
    PACIFIC_TZ, REPORT_CHAT_ID, ADMIN_ID, VALID_ROUTES
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"ADMIN_ID loaded: {ADMIN_ID} (type: {type(ADMIN_ID).__name__})")
logger.info(f"WHITELIST loaded: {WHITELIST}")
logger.info(f"REPORT_CHAT_ID loaded: {REPORT_CHAT_ID}")


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


def build_admin_driver_block(name, user_data, driver_rate, week_start):
    lines = [f"👤 *{name}*  (rate: ${driver_rate:.2f}/pkg)"]
    user_total = 0
    for day_num, routes in sorted(user_data.items()):
        day_total = sum(routes.values())
        user_total += day_total
        day_dt = week_start + timedelta(days=day_num)
        lines.append(f"  *{APP_DAY_NAMES[day_num]} {format_date(day_dt)}* — {day_total} pkgs")
        for route, count in sorted(routes.items()):
            lines.append(f"    Route {route}: {count}")
    company_rev = user_total * COMPANY_RATE
    driver_cost = user_total * driver_rate
    profit = company_rev - driver_cost
    lines.append(f"  Packages: *{user_total}*")
    lines.append(f"  Company revenue: ${company_rev:.2f}")
    lines.append(f"  Driver pay: *${driver_cost:.2f}*")
    lines.append(f"  Your profit: *${profit:.2f}*")
    return lines, user_total, company_rev, driver_cost


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

    keyboard.append([InlineKeyboardButton("💰 Driver Rates", callback_data="admin_rates")])

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

    if data == "admin_rates":
        all_rates = get_all_rates()
        lines = ["*Driver Rates:*\n"]
        for uid, name in WHITELIST.items():
            rate = all_rates.get(uid, DEFAULT_DRIVER_RATE)
            tag = " (default)" if uid not in all_rates else ""
            lines.append(f"  *{name}* — ${rate:.2f}/pkg{tag}")
            lines.append(f"  ID: `{uid}`\n")
        lines.append(f"Company rate: *${COMPANY_RATE:.2f}/pkg*")
        await query.message.reply_text("\n".join(lines), parse_mode='Markdown')
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
                block, user_total, company_rev, driver_cost = build_admin_driver_block(name, user_data, driver_rate, week_start)
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
            block, user_total, company_rev, driver_cost = build_admin_driver_block(name, user_data, driver_rate, week_start)
            profit = company_rev - driver_cost
            lines = [f"*{name} — {week_range}*\n"] + block
            lines.append(f"\nYour profit: *${profit:.2f}*")

        await query.message.reply_text("\n".join(lines), parse_mode='Markdown')


# ─── Handle messages & keyboard buttons ──────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("You don't have access to this bot.")
        return

    text = update.message.text.strip()

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
        block, user_total, company_rev, driver_cost = build_admin_driver_block(name, user_data, driver_rate, week_start)
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
