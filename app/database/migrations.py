from app.database.db import db


async def migrate():
    async with await db.connect() as conn:

        await conn.executescript('''

        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER UNIQUE,
            title TEXT,
            type TEXT
        );

        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_uuid TEXT,
            title TEXT,
            post_chat_id INTEGER,
            winners_count INTEGER,
            prizes TEXT,
            participants_count INTEGER DEFAULT 0,
            status TEXT
        );

        CREATE TABLE IF NOT EXISTS giveaway_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id INTEGER,
            user_id INTEGER,
            username TEXT
        );

        ''')

        await conn.commit()
