import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from database import init_db
from scheduler import scheduler
from handlers import admin_private, roulette

# Настраиваем логирование, чтобы все действия и ошибки писались в панель Bothost
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)

async def main():
    # 1. Инициализируем базу данных (создаем таблицы, если их нет)
    logging.info("⏳ Инициализация базы данных...")
    await init_db()
    logging.info("✅ База данных успешно инициализирована!")

    # 2. Запускаем планировщик задач для автоматического закрытия рулетки
    if not scheduler.running:
        scheduler.start()
        logging.info("⏰ Планировщик задач APScheduler успешно запущен!")

    # 3. Инициализируем бота и диспетчер
    bot = Bot(
        token=BOT_TOKEN, 
        default_bot_properties=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    dp = Dispatcher()

    # 4. Регистрируем роутеры СТРОГО в правильном порядке
    # Сначала приватная панель администратора, затем обработчик групповой рулетки
    dp.include_router(admin_private.router)
    dp.include_router(roulette.router)

    logging.info("🚀 Бот успешно запущен и готов к работе!")
    
    # 5. Запускаем polling (удаляем старые вебхуки, если они были, чтобы избежать конфликтов)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Бот остановлен!")
