import asyncio
import logging
import os
import sys
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_ADMIN_ID_STR = os.getenv("MAIN_ADMIN_ID")
PORT = int(os.getenv("PORT", 8080))  # Bothost задаёт PORT

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не задан")
    sys.exit(1)
if not MAIN_ADMIN_ID_STR:
    logger.error("❌ MAIN_ADMIN_ID не задан")
    sys.exit(1)
try:
    MAIN_ADMIN_ID = int(MAIN_ADMIN_ID_STR)
except ValueError:
    logger.error("❌ MAIN_ADMIN_ID должен быть числом")
    sys.exit(1)

async def health_check(request):
    return web.Response(text="OK")

async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    from roulette import setup_routers, init_db, queue_worker, clean_old_roulettes

    init_db()
    setup_routers(dp, bot, MAIN_ADMIN_ID)

    # Фоновые задачи
    asyncio.create_task(queue_worker(bot))
    asyncio.create_task(clean_old_roulettes(bot))

    # Запуск HTTP-сервера для health-check
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health-check server started on port {PORT}")

    # Запуск поллинга
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
