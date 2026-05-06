import logging
from datetime import datetime, timedelta
import pytz
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from data import init_db, record_delivery, get_week_data
from config import BOT_TOKEN, WHITELIST, RATE_PER_PACKAGE, PACIFIC_TZ, REPORT_CHAT_ID, VALID_ROUTES

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def format_date(dt: datetime) -> str:
    return dt.strftime("%b %-d")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in WHITELIST:
        await update.message.reply_text("⛔ You don't have access to this bot.")
        return
    name = WHITELIST[user_id]
    routes_str = ", ".join(str(r) for r in VALID_ROUTES)
    await update.message.reply_text(
        f"👋 Hey, {name}!\n\n"
        f"To log deliveries, send your route number and package count:\n"
        f"`<route>, <packages>`\n\n"
        f"Example: `2, 63`\n"
        f"Routes available: {routes_str}\n\n"
        f"Commands:\n"
        f"/mystats — your stats for this week\n"
        f"/report — full weekly report for all drivers",
        parse_mode='Markdown'
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in WHITELIST:
        await update.message.reply_text("⛔ You don't have access to this bot.")
        return

    text = update.message.text.strip()
    parts = [p.strip() for p in text.split(",")]

    if len(parts) != 2:
        routes_str = ", ".join(str(r) for r in VALID_ROUTES)
        await update.message.reply_text(
            f"❌ Wrong format. Please send: `<route>, <packages>`\n"
            f"Example: `2, 63`\n"
            f"Available routes: {routes_str}",
            parse_mode='Markdown'
        )
        return

    try:
        route = int(parts[0])
        count = int(parts[1])
        if count < 0 or route < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Both route and package count must be positive numbers.\n"
            "Example: `2, 63`",
            parse_mode='Markdown'
        )
        return

    if route not in VALID_ROUTES:
        routes_str = ", ".join(str(r) for r in VALID_ROUTES)
        await update.message.reply_text(
            f"❌ Route *{route}* doesn't exist. Available routes: {routes_str}",
            parse_mode='Markdown'
        )
        return

    now = datetime.now(PACIFIC_TZ)
    name = WHITELIST[user_id]
    day_name = DAY_NAMES[now.weekday()]
    date_str = format_date(now)
    earnings = count * RATE_PER_PACKAGE

    record_delivery(user_id, route, count, now)

    await update.message.reply_text(
        f"✅ Saved! {name}, {day_name} {date_str} — Route {route}: *{count}* packages = *${earnings:.2f}*",
        parse_mode='Markdown'
    )


async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in WHITELIST:
        await update.message.reply_text("⛔ You don't have access to this bot.")
        return

    name = WHITELIST[user_id]
    now = datetime.now(PACIFIC_TZ)
    week_data = get_week_data(now)
    user_data = week_data.get(user_id, {})

    if not user_data:
        await update.message.reply_text(f"📭 {name}, no data for this week yet.")
        return

    lines = [f"📊 *Your week, {name}:*\n"]
    total = 0
    week_start = now - timedelta(days=now.weekday())

    for day_num, routes in sorted(user_data.items()):
        day_total = sum(routes.values())
        total += day_total
        day_dt = week_start + timedelta(days=day_num)
        date_str = format_date(day_dt)
        lines.append(f"*{DAY_NAMES[day_num]} {date_str}* — {day_total} packages")
        for route, count in sorted(routes.items()):
            lines.append(f"  Route {route}: {count}")

    lines.append(f"\n📦 Total: *{total}* packages")
    lines.append(f"💰 Earnings: *${total * RATE_PER_PACKAGE:.2f}*")

    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')


async def send_weekly_report(context: ContextTypes.DEFAULT_TYPE, chat_id=None):
    now = datetime.now(PACIFIC_TZ)
    week_data = get_week_data(now)

    target_chat = chat_id or REPORT_CHAT_ID
    if not target_chat:
        logger.warning("No REPORT_CHAT_ID configured")
        return

    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=6)
    week_range = f"{week_start.strftime('%b %-d')} – {week_end.strftime('%b %-d, %Y')}"

    lines = [f"📋 *WEEKLY REPORT*", f"🗓 {week_range}\n"]
    grand_total = 0
    any_data = False

    for user_id_int, name in WHITELIST.items():
        user_data = week_data.get(user_id_int, {})
        if not user_data:
            continue
        any_data = True

        user_total = 0
        user_lines = [f"👤 *{name}*"]

        for day_num, routes in sorted(user_data.items()):
            day_total = sum(routes.values())
            user_total += day_total
            day_dt = week_start + timedelta(days=day_num)
            date_str = format_date(day_dt)
            user_lines.append(f"  *{DAY_NAMES[day_num]} {date_str}* — {day_total} pkgs")
            for route, count in sorted(routes.items()):
                user_lines.append(f"    Route {route}: {count}")

        user_earnings = user_total * RATE_PER_PACKAGE
        user_lines.append(f"  Total: *{user_total}* packages = *${user_earnings:.2f}*")
        grand_total += user_total
        lines += user_lines
        lines.append("")

    if not any_data:
        await context.bot.send_message(chat_id=target_chat, text="📭 No data for this week yet.")
        return

    lines.append("─────────────────")
    lines.append(f"📦 *Grand total: {grand_total} packages*")
    lines.append(f"💰 *Total earnings: ${grand_total * RATE_PER_PACKAGE:.2f}*")

    await context.bot.send_message(
        chat_id=target_chat,
        text="\n".join(lines),
        parse_mode='Markdown'
    )


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in WHITELIST:
        await update.message.reply_text("⛔ You don't have access to this bot.")
        return
    await send_weekly_report(context, chat_id=update.effective_chat.id)


async def scheduled_report(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Sending scheduled weekly report...")
    await send_weekly_report(context)


def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mystats", my_stats))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = AsyncIOScheduler(timezone=PACIFIC_TZ)
    scheduler.add_job(
        scheduled_report,
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
