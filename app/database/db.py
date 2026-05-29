import aiosqlite

from app.core.config import config


class Database:

    async def connect(self):
        return await aiosqlite.connect(config.database_path)


db = Database()
