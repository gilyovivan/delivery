import os
import pytz

# ─── BOT TOKEN ───────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ─── TIMEZONE ────────────────────────────────────────────────────────────────
PACIFIC_TZ = pytz.timezone("America/Los_Angeles")

# ─── COMPANY RATE (what the company pays you per package) ────────────────────
COMPANY_RATE = 1.70

# ─── DEFAULT DRIVER RATE (fallback if no custom rate set) ────────────────────
DEFAULT_DRIVER_RATE = 0.80

# ─── REPORT CHAT ─────────────────────────────────────────────────────────────
REPORT_CHAT_ID = int(os.getenv("REPORT_CHAT_ID", "320394840"))  # Set this!

# ─── ADMIN USER ID ───────────────────────────────────────────────────────────
# Your personal Telegram ID — only you will see admin commands and profit report
ADMIN_ID = int(os.getenv("ADMIN_ID", "320394840"))

# ─── VALID ROUTES ────────────────────────────────────────────────────────────
VALID_ROUTES = {1, 2, 3}

# ─── WHITELIST ───────────────────────────────────────────────────────────────
# Format: { telegram_user_id (int): "Display Name" }
WHITELIST = {
     320394840: "IVAN",
     327077236: "TAMIRIS"
}
