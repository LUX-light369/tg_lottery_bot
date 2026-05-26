import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot_data.db")
DEFAULT_TZ = "Asia/Novosibirsk"

# Пути к разным шрифтам оформления
FONT_TITLE = os.path.join("fonts", "bebas_neue.ttf")
FONT_WINNERS = os.path.join("fonts", "pricedown.ttf")
FONT_INFO = os.path.join("fonts", "inter.ttf")
