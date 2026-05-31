import asyncio
import logging
import os
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(level=logging.INFO)

# Проверка переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_ADMIN_ID_STR = os.getenv("MAIN_ADMIN_ID")

if not BOT_TOKEN:
    logging.error("❌ Не задана переменная BOT_TOKEN. Добавьте её в настройках окружения.")
    sys.exit(1)

if not MAIN_ADMIN_ID_STR:
    logging.error("❌ Не задана переменная MAIN_ADMIN_ID. Добавьте её в настройках окружения.")
    sys.exit(1)

try:
    MAIN_ADMIN_ID = int(MAIN_ADMIN_ID_STR)
except ValueError:
    logging.error("❌ MAIN_ADMIN_ID должен быть числом (ваш Telegram user ID).")
    sys.exit(1)

async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    from roulette import setup_routers, init_db, queue_worker, clean_old_roulettes

    init_db()
    setup_routers(dp, bot, MAIN_ADMIN_ID)

    asyncio.create_task(queue_worker(bot))
    asyncio.create_task(clean_old_roulettes(bot))

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
