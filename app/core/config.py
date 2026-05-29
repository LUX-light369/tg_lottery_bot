from dataclasses import dataclass
from dotenv import load_dotenv
import os

load_dotenv()


@dataclass
class Config:
    bot_token: str
    main_admin_id: int
    database_path: str
    timezone: str


config = Config(
    bot_token=os.getenv("BOT_TOKEN"),
    main_admin_id=int(os.getenv("MAIN_ADMIN_ID")),
    database_path=os.getenv("DATABASE_PATH", "data/bot.db"),
    timezone=os.getenv("TIMEZONE", "Asia/Novosibirsk")
)
