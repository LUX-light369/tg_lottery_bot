import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID"))

if not BOT_TOKEN or not MAIN_ADMIN_ID:
    raise ValueError("BOT_TOKEN and MAIN_ADMIN_ID must be set in .env file")

logging.basicConfig(level=logging.INFO)

async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Импорты вынесены внутрь, чтобы избежать циклических зависимостей
    from roulette import setup_routers, init_db, queue_worker, clean_old_roulettes

    # Инициализация базы данных
    init_db()

    # Подключение роутеров и передача ID главного админа
    setup_routers(dp, bot, MAIN_ADMIN_ID)

    # Запуск фоновых задач
    asyncio.create_task(queue_worker(bot))
    asyncio.create_task(clean_old_roulettes(bot))

    # Запуск поллинга
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
