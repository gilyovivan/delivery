import os
import pytz

# ─── BOT TOKEN ───────────────────────────────────────────────────────────────
# Get from @BotFather on Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ─── TIMEZONE ────────────────────────────────────────────────────────────────
PACIFIC_TZ = pytz.timezone("America/Los_Angeles")

# ─── RATE ────────────────────────────────────────────────────────────────────
RATE_PER_PACKAGE = 1.7  # $ per package

# ─── REPORT CHAT ─────────────────────────────────────────────────────────────
# The chat ID where the bot will send the automatic Sunday report.
# Can be a group chat ID or a personal chat ID.
# To get your chat ID: send /start to the bot and check logs, or use @userinfobot
REPORT_CHAT_ID = int(os.getenv("REPORT_CHAT_ID", "0"))  # Set this!

# ─── WHITELIST ───────────────────────────────────────────────────────────────
# Format: { telegram_user_id (int): "Display Name" }
# To get a user's Telegram ID: ask them to message @userinfobot
#
# IMPORTANT: Replace these with real Telegram user IDs!
WHITELIST = {
    123456789: "Алексей",
    987654321: "Мария",
    111222333: "Дмитрий",
    # Add more users here:
    # 444555666: "Иван",
}
