import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", 0))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///giftbot.db")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Novosibirsk")
MSG_DELAY = float(os.getenv("MSG_DELAY", "2.0"))
