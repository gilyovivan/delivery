import os
import pytz

PACIFIC_TZ = pytz.timezone("America/Los_Angeles")

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
REPORT_CHAT_ID = int(os.getenv("REPORT_CHAT_ID", "0"))

COMPANY_RATE = float(os.getenv("COMPANY_RATE", "1.70"))
DEFAULT_DRIVER_RATE = float(os.getenv("DEFAULT_DRIVER_RATE", "0.80"))

VALID_ROUTES = {1, 2, 3}

WHITELIST = {
    int(uid): name
    for uid, name in (
        pair.split(":", 1)
        for pair in os.getenv("WHITELIST", "").split(",")
        if ":" in pair
    )
}
