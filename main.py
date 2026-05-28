import asyncio, logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
from database.engine import engine, Base
from middleware.session import DatabaseSessionMiddleware
from handlers import private, chat
from services.scheduler import setup_scheduler

async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрируем middleware для сессии БД
    dp.update.middleware(DatabaseSessionMiddleware())

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    dp.include_router(private.router)
    dp.include_router(chat.router)

    scheduler = setup_scheduler()

    # Очистка старых данных раз в сутки
    async def cleanup():
        from sqlalchemy import delete
        from database.models import Giveaway, Roulette
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(days=30)
        async with engine.begin() as conn:
            await conn.execute(delete(Giveaway).where(Giveaway.created_at < cutoff))
            await conn.execute(delete(Roulette).where(Roulette.created_at < cutoff))
    scheduler.add_job(cleanup, 'interval', days=1)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
