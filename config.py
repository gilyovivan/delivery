import os
import pytz

# ─── BOT TOKEN ───────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "8661067926:AAEQKbIW5FLsTJv0BPfUl_3twvetPy8dy7s")

# ─── TIMEZONE ────────────────────────────────────────────────────────────────
PACIFIC_TZ = pytz.timezone("America/Los_Angeles")

# ─── RATE ────────────────────────────────────────────────────────────────────
RATE_PER_PACKAGE = 1.7  # $ per package

# ─── REPORT CHAT ─────────────────────────────────────────────────────────────
REPORT_CHAT_ID = int(os.getenv("REPORT_CHAT_ID", "320394840"))  # Set this!

# ─── VALID ROUTES ────────────────────────────────────────────────────────────
# Add or remove route numbers here as needed
VALID_ROUTES = {1, 2, 3}

# ─── WHITELIST ───────────────────────────────────────────────────────────────
# Format: { telegram_user_id (int): "Display Name" }
WHITELIST = {
    320394840: "IVAN",
    # Add more drivers here:
    # 444555666: "Ivan",
}
