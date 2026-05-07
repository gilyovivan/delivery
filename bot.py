import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
Application, CommandHandler, MessageHandler,
filters, ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from data import init_db, record_delivery, get_week_data, set_driver_rate, get_driver_rate, get_all_rates
from config import (
BOT_TOKEN, WHITELIST, COMPANY_RATE, DEFAULT_DRIVER_RATE,
PACIFIC_TZ, REPORT_CHAT_ID, ADMIN_ID, VALID_ROUTES
)

logging.basicConfig(
format=’%(asctime)s - %(name)s - %(levelname)s - %(message)s’,
level=logging.INFO
)
logger = logging.getLogger(**name**)

DAY_NAMES = [“Mon”, “Tue”, “Wed”, “Thu”, “Fri”, “Sat”, “Sun”]

# Log on startup so we can verify values

logger.info(f”ADMIN_ID loaded: {ADMIN_ID} (type: {type(ADMIN_ID).**name**})”)
logger.info(f”WHITELIST loaded: {WHITELIST}”)
logger.info(f”REPORT_CHAT_ID loaded: {REPORT_CHAT_ID}”)

def format_date(dt: datetime) -> str:
return dt.strftime(”%b %-d”)

def is_admin(user_id: int) -> bool:
result = int(user_id) == int(ADMIN_ID)
logger.info(f”is_admin check: user_id={user_id} ({type(user_id).**name**}), ADMIN_ID={ADMIN_ID} ({type(ADMIN_ID).**name**}), result={result}”)
return result

def is_authorized(user_id: int) -> bool:
return user_id in WHITELIST or is_admin(user_id)

# ─── /start ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = update.effective_user.id
if not is_authorized(user_id):
await update.message.reply_text(“⛔ You don’t have access to this bot.”)
return

```
name = WHITELIST.get(user_id, "Admin")
routes_str = ", ".join(str(r) for r in sorted(VALID_ROUTES))

msg = (
    f"👋 Hey, {name}!\n\n"
    f"To log deliveries send: `<route>, <packages>`\n"
    f"Example: `2, 63`\n"
    f"Available routes: {routes_str}\n\n"
    f"Commands:\n"
    f"/mystats — your stats for this week\n"
    f"/report — weekly report"
)

if is_admin(user_id):
    msg += (
        f"\n\n🔧 *Admin commands:*\n"
        f"/setrate <user\\_id> <rate> — set driver rate\n"
        f"  Example: `/setrate 123456789 0.80`\n"
        f"/rates — view all driver rates\n"
        f"/adminreport — full report with profit breakdown"
    )

await update.message.reply_text(msg, parse_mode='Markdown')
```

# ─── Handle delivery input ────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = update.effective_user.id
if not is_authorized(user_id):
await update.message.reply_text(“⛔ You don’t have access to this bot.”)
return

```
text = update.message.text.strip()
parts = [p.strip() for p in text.split(",")]

if len(parts) != 2:
    routes_str = ", ".join(str(r) for r in sorted(VALID_ROUTES))
    await update.message.reply_text(
        f"❌ Wrong format. Send: `<route>, <packages>`\n"
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
        "❌ Both values must be positive numbers.\nExample: `2, 63`",
        parse_mode='Markdown'
    )
    return

if route not in VALID_ROUTES:
    routes_str = ", ".join(str(r) for r in sorted(VALID_ROUTES))
    await update.message.reply_text(
        f"❌ Route *{route}* doesn't exist. Available: {routes_str}",
        parse_mode='Markdown'
    )
    return

now = datetime.now(PACIFIC_TZ)
name = WHITELIST.get(user_id, "Admin")
day_name = DAY_NAMES[now.weekday()]
date_str = format_date(now)
driver_rate = get_driver_rate(user_id, DEFAULT_DRIVER_RATE)
earnings = count * driver_rate

record_delivery(user_id, route, count, now)

await update.message.reply_text(
    f"✅ Saved! {name}, {day_name} {date_str} — Route {route}: *{count}* packages = *${earnings:.2f}*",
    parse_mode='Markdown'
)
```

# ─── /mystats ────────────────────────────────────────────────────────────────

async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = update.effective_user.id
logger.info(f”/mystats called by user_id={user_id}”)
if not is_authorized(user_id):
await update.message.reply_text(“⛔ You don’t have access to this bot.”)
return

```
name = WHITELIST.get(user_id, "Admin")
now = datetime.now(PACIFIC_TZ)
week_data = get_week_data(now)
user_data = week_data.get(user_id, {})

if not user_data:
    await update.message.reply_text(f"📭 {name}, no data for this week yet.")
    return

driver_rate = get_driver_rate(user_id, DEFAULT_DRIVER_RATE)
week_start = now - timedelta(days=now.weekday())
lines = [f"📊 *Your week, {name}:*\n"]
total = 0

for day_num, routes in sorted(user_data.items()):
    day_total = sum(routes.values())
    total += day_total
    day_dt = week_start + timedelta(days=day_num)
    lines.append(f"*{DAY_NAMES[day_num]} {format_date(day_dt)}* — {day_total} packages")
    for route, count in sorted(routes.items()):
        lines.append(f"  Route {route}: {count}")

lines.append(f"\n📦 Total: *{total}* packages")
lines.append(f"💰 Your earnings: *${total * driver_rate:.2f}*  (${driver_rate}/pkg)")

await update.message.reply_text("\n".join(lines), parse_mode='Markdown')
```

# ─── /report (driver version) ────────────────────────────────────────────────

async def driver_report(context, chat_id, user_id, week_data, now):
name = WHITELIST.get(user_id, “Driver”)
user_data = week_data.get(user_id, {})
driver_rate = get_driver_rate(user_id, DEFAULT_DRIVER_RATE)
week_start = now - timedelta(days=now.weekday())
week_end = week_start + timedelta(days=6)
week_range = f”{format_date(week_start)} – {format_date(week_end)}, {now.year}”

```
if not user_data:
    await context.bot.send_message(chat_id=chat_id, text=f"📭 {name}, no data for this week yet.")
    return

lines = [f"📋 *Weekly Report — {name}*", f"🗓 {week_range}\n"]
total = 0

for day_num, routes in sorted(user_data.items()):
    day_total = sum(routes.values())
    total += day_total
    day_dt = week_start + timedelta(days=day_num)
    lines.append(f"*{DAY_NAMES[day_num]} {format_date(day_dt)}* — {day_total} packages")
    for route, count in sorted(routes.items()):
        lines.append(f"  Route {route}: {count}")

lines.append(f"\n📦 Total: *{total}* packages")
lines.append(f"💰 Your earnings: *${total * driver_rate:.2f}*")

await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode='Markdown')
```

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = update.effective_user.id
if not is_authorized(user_id):
await update.message.reply_text(“⛔ You don’t have access to this bot.”)
return
now = datetime.now(PACIFIC_TZ)
week_data = get_week_data(now)
await driver_report(context, update.effective_chat.id, user_id, week_data, now)

# ─── /adminreport ────────────────────────────────────────────────────────────

async def admin_report(context, chat_id, now=None):
if now is None:
now = datetime.now(PACIFIC_TZ)

```
week_data = get_week_data(now)
week_start = now - timedelta(days=now.weekday())
week_end = week_start + timedelta(days=6)
week_range = f"{format_date(week_start)} – {format_date(week_end)}, {now.year}"

lines = [f"🔐 *ADMIN WEEKLY REPORT*", f"🗓 {week_range}\n"]

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
    user_total = 0
    user_lines = [f"👤 *{name}*  (rate: ${driver_rate:.2f}/pkg)"]

    for day_num, routes in sorted(user_data.items()):
        day_total = sum(routes.values())
        user_total += day_total
        day_dt = week_start + timedelta(days=day_num)
        user_lines.append(f"  *{DAY_NAMES[day_num]} {format_date(day_dt)}* — {day_total} pkgs")
        for route, count in sorted(routes.items()):
            user_lines.append(f"    Route {route}: {count}")

    company_rev = user_total * COMPANY_RATE
    driver_cost = user_total * driver_rate
    profit = company_rev - driver_cost

    user_lines.append(f"  Packages: *{user_total}*")
    user_lines.append(f"  Company revenue: ${company_rev:.2f}")
    user_lines.append(f"  Driver pay: *${driver_cost:.2f}*")
    user_lines.append(f"  Your profit: *${profit:.2f}*")

    grand_packages += user_total
    grand_company_revenue += company_rev
    grand_driver_cost += driver_cost

    lines += user_lines
    lines.append("")

if not any_data:
    await context.bot.send_message(chat_id=chat_id, text="📭 No data for this week yet.")
    return

grand_profit = grand_company_revenue - grand_driver_cost
lines.append("─────────────────")
lines.append(f"📦 *Total packages: {grand_packages}*")
lines.append(f"💵 Company revenue: ${grand_company_revenue:.2f}")
lines.append(f"💸 Total driver pay: ${grand_driver_cost:.2f}")
lines.append(f"✅ *Your profit: ${grand_profit:.2f}*")

await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode='Markdown')
```

async def admin_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = update.effective_user.id
logger.info(f”/adminreport called by user_id={user_id}”)
if not is_admin(user_id):
await update.message.reply_text(“⛔ Admin only.”)
return
await admin_report(context, update.effective_chat.id)

# ─── /setrate ────────────────────────────────────────────────────────────────

async def set_rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = update.effective_user.id
if not is_admin(user_id):
await update.message.reply_text(“⛔ Admin only.”)
return

```
args = context.args
if len(args) != 2:
    await update.message.reply_text(
        "Usage: `/setrate <user_id> <rate>`\nExample: `/setrate 123456789 0.80`",
        parse_mode='Markdown'
    )
    return

try:
    target_id = int(args[0])
    rate = float(args[1])
    if rate <= 0:
        raise ValueError
except ValueError:
    await update.message.reply_text("❌ Invalid user_id or rate.")
    return

if target_id not in WHITELIST:
    await update.message.reply_text(f"❌ User `{target_id}` not found in whitelist.", parse_mode='Markdown')
    return

set_driver_rate(target_id, rate)
name = WHITELIST[target_id]
await update.message.reply_text(
    f"✅ Rate updated!\n*{name}* → *${rate:.2f}/package*",
    parse_mode='Markdown'
)
```

# ─── /rates ──────────────────────────────────────────────────────────────────

async def rates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = update.effective_user.id
if not is_admin(user_id):
await update.message.reply_text(“⛔ Admin only.”)
return

```
all_rates = get_all_rates()
lines = ["💰 *Driver Rates:*\n"]

for uid, name in WHITELIST.items():
    rate = all_rates.get(uid, DEFAULT_DRIVER_RATE)
    tag = " _(default)_" if uid not in all_rates else ""
    lines.append(f"  *{name}* — ${rate:.2f}/pkg{tag}")
    lines.append(f"  ID: `{uid}`")
    lines.append("")

lines.append(f"🏢 Company rate: *${COMPANY_RATE:.2f}/pkg*")
await update.message.reply_text("\n".join(lines), parse_mode='Markdown')
```

# ─── Scheduled reports ───────────────────────────────────────────────────────

async def scheduled_reports(context: ContextTypes.DEFAULT_TYPE):
logger.info(“Sending scheduled weekly reports…”)
now = datetime.now(PACIFIC_TZ)
week_data = get_week_data(now)

```
for uid in WHITELIST:
    try:
        await driver_report(context, uid, uid, week_data, now)
    except Exception as e:
        logger.warning(f"Could not send report to user {uid}: {e}")

if REPORT_CHAT_ID:
    await admin_report(context, REPORT_CHAT_ID, now)
```

# ─── Main ────────────────────────────────────────────────────────────────────

def main():
init_db()
app = Application.builder().token(BOT_TOKEN).build()

```
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("mystats", my_stats))
app.add_handler(CommandHandler("report", report_command))
app.add_handler(CommandHandler("adminreport", admin_report_command))
app.add_handler(CommandHandler("setrate", set_rate_command))
app.add_handler(CommandHandler("rates", rates_command))
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
```

if **name** == ‘**main**’:
main()