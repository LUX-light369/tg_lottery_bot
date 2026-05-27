import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from database import init_db
from scheduler import scheduler
from handlers import admin_private, roulette, giveaway
from utils.anti_flood import AntiFloodMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)

async def main():
    await init_db()

    if not scheduler.running:
        scheduler.start()

    bot = Bot(token=BOT_TOKEN, default_bot_properties=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Подключаем защиту от флуда и спама сообщениями в группах
    dp.message.middleware(AntiFloodMiddleware(delay=2.0))

    # Регистрация роутеров
    dp.include_router(admin_private.router)
    dp.include_router(roulette.router)
    dp.include_router(giveaway.router)

    logging.info("🚀 Сборка запущена успешно! Бот готов обрабатывать логику.")
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Бот остановлен!")
