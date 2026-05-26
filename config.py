import os
from dotenv import load_dotenv

load_dotenv()

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# База данных
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot_data.db")

# Таймзона по умолчанию
DEFAULT_TZ = "Asia/Novosibirsk"

# Чтение ADMIN_ID из переменных хостинга. Если переменной нет, подставит 0 (чтобы не падать).
# Замени 123456789 на свой реальный ID в Telegram, если не хочешь использовать панель хостинга.
ADMIN_ID = int(os.getenv("ADMIN_ID", 123456789))

# Пути к шрифтам оформления внутри контейнера
FONT_TITLE = os.path.join("fonts", "bebas_neue.ttf")
FONT_WINNERS = os.path.join("fonts", "pricedown.ttf")
FONT_INFO = os.path.join("fonts", "inter.ttf")
