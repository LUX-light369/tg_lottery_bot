import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot_data.db")
DEFAULT_TZ = "Asia/Novosibirsk"
FONT_PATH = "font.ttf"  # Положите любой .ttf шрифт в корень (например, Arial Black)
