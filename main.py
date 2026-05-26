import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from database import init_db, clean_expired_bans
from scheduler import scheduler
from handlers import roulette, admin_private
from utils.anti_flood import ThrottlingMiddleware

logging.basicConfig(level=logging.INFO)

async def main():
    # 1. Инициализируем структуры базы данных
    await init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # 2. Подключаем глобальную защиту от спама (Троттлинг)
    dp.message.middleware(ThrottlingMiddleware(limit=1.5))

    # 3. Регистрация роутеров обработчиков команд
    dp.include_router(admin_private.router)
    dp.include_router(roulette.router)

    # 4. Настройка периодической очистки старых данных (раз в сутки)
    scheduler.add_job(clean_expired_bans, 'interval', days=1)
    scheduler.start()

    logging.info("🚀 Бот успешно запущен и готов к работе!")
    
    # 5. Запуск бесконечного цикла поллинга обновлений Telegram
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        async_loop = asyncio.get_event_loop()
        async_loop.run_until_complete(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Бот остановлен.")
