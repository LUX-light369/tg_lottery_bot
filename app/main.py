import asyncio

from app.core.bot import bot
from app.core.dispatcher import dp
from app.database.migrations import migrate
from app.handlers.start import router as start_router
from app.handlers.chats import router as chats_router
from app.modules.giveaway import router as giveaway_router


async def main():
    await migrate()

    dp.include_router(start_router)
    dp.include_router(chats_router)
    dp.include_router(giveaway_router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
