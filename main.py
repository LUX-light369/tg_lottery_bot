import asyncio
import logging
import os
import signal
import sys
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_ADMIN_ID_STR = os.getenv("MAIN_ADMIN_ID")
PORT = int(os.getenv("PORT", "8080"))

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
    return web.json_response({"status": "ok"})

async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    from roulette import setup_routers, init_db, queue_worker, clean_old_roulettes, set_bot_username

    init_db()

    # Получаем username бота и передаём в roulette
    me = await bot.me()
    set_bot_username(me.username)

    setup_routers(dp, bot, MAIN_ADMIN_ID)

    asyncio.create_task(queue_worker(bot))
    asyncio.create_task(clean_old_roulettes(bot))

    # HTTP server
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health-check server listening on port {PORT}")

    loop = asyncio.get_running_loop()
    def shutdown():
        logger.info("Shutting down...")
        for task in asyncio.all_tasks(loop):
            task.cancel()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, shutdown)
        except NotImplementedError:
            pass

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await runner.cleanup()
        logger.info("Bot stopped")

if __name__ == "__main__":
    asyncio.run(main())
