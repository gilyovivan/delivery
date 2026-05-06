import os
import json
import logging
from datetime import datetime, time
import pytz
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from data import init_db, record_delivery, get_week_data
from config import BOT_TOKEN, WHITELIST, RATE_PER_PACKAGE, PACIFIC_TZ, REPORT_CHAT_ID

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in WHITELIST:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return
    name = WHITELIST[user_id]
    await update.message.reply_text(
        f"👋 Привет, {name}!\n\n"
        f"Просто отправь число — количество развезённых посылок за сегодня.\n"
        f"Например: `62`\n\n"
        f"Команды:\n"
        f"/mystats — твоя статистика за эту неделю\n"
        f"/report — отчёт по всем курьерам за неделю",
        parse_mode='Markdown'
    )


async def handle_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in WHITELIST:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    text = update.message.text.strip()
    try:
        count = int(text)
        if count < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, отправь целое положительное число.")
        return

    now = datetime.now(PACIFIC_TZ)
    weekday = now.weekday()  # 0=Mon, 6=Sun

    # Allow Mon-Sat (0-5) and Sun (6) for flexibility
    name = WHITELIST[user_id]
    day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][weekday]

    record_delivery(user_id, count, now)
    earnings = count * RATE_PER_PACKAGE

    await update.message.reply_text(
        f"✅ Записано! {name}, {day_name}: *{count}* посылок = *${earnings:.2f}*",
        parse_mode='Markdown'
    )


async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in WHITELIST:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    name = WHITELIST[user_id]
    now = datetime.now(PACIFIC_TZ)
    week_data = get_week_data(now)

    user_data = week_data.get(user_id, {})
    if not user_data:
        await update.message.reply_text(f"📭 {name}, на этой неделе данных ещё нет.")
        return

    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    lines = [f"📊 *Твоя неделя, {name}:*\n"]
    total = 0
    for day_num, count in sorted(user_data.items()):
        lines.append(f"  {day_names[day_num]}: {count} посылок")
        total += count

    lines.append(f"\n📦 Итого: *{total}* посылок")
    lines.append(f"💰 Сумма: *${total * RATE_PER_PACKAGE:.2f}*")

    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')


async def send_weekly_report(context: ContextTypes.DEFAULT_TYPE, chat_id=None):
    now = datetime.now(PACIFIC_TZ)
    week_data = get_week_data(now)

    target_chat = chat_id or REPORT_CHAT_ID
    if not target_chat:
        logger.warning("No REPORT_CHAT_ID configured and no chat_id provided")
        return

    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    lines = ["📋 *ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ*\n"]

    grand_total = 0
    all_users_have_data = False

    for user_id_int, name in WHITELIST.items():
        user_data = week_data.get(user_id_int, {})
        if not user_data:
            continue
        all_users_have_data = True

        user_total = sum(user_data.values())
        grand_total += user_total
        user_earnings = user_total * RATE_PER_PACKAGE

        lines.append(f"👤 *{name}*")
        for day_num, count in sorted(user_data.items()):
            lines.append(f"  {day_names[day_num]}: {count} посылок")
        lines.append(f"  Итого: {user_total} шт. = ${user_earnings:.2f}\n")

    if not all_users_have_data:
        await context.bot.send_message(
            chat_id=target_chat,
            text="📭 За эту неделю данных ещё нет."
        )
        return

    lines.append(f"─────────────────")
    lines.append(f"📦 *Всего посылок: {grand_total}*")
    lines.append(f"💰 *Общая сумма: ${grand_total * RATE_PER_PACKAGE:.2f}*")

    # Add week range
    week_start = now - __import__('datetime').timedelta(days=now.weekday())
    lines.append(f"\n🗓 Неделя: {week_start.strftime('%d.%m')} – {now.strftime('%d.%m.%Y')}")

    await context.bot.send_message(
        chat_id=target_chat,
        text="\n".join(lines),
        parse_mode='Markdown'
    )


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in WHITELIST:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return
    await send_weekly_report(context, chat_id=update.effective_chat.id)


async def scheduled_report(context: ContextTypes.DEFAULT_TYPE):
    """Called automatically every Sunday at 7:30 PM Pacific"""
    logger.info("Sending scheduled weekly report...")
    await send_weekly_report(context)


def main():
    init_db()  # Create DB table on startup
    app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mystats", my_stats))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_number))

    # Scheduler for Sunday 7:30 PM Pacific
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
